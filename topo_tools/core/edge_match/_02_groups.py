"""Runs extend's pipeline once per parent group, in an isolated subprocess.

Data crosses the process boundary as small Parquet files, never a shared
connection (DuckDB files are single-writer).
"""

import contextlib
import multiprocessing
import shutil
from logging import INFO, basicConfig, getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_no_erosion, check_valid_topology
from topo_tools.core.duckdb_utils import (
    get_connection,
    log_file,
    spawn_worker,
    worker_result,
)
from topo_tools.core.edge_extend import _02_lines as lines
from topo_tools.core.edge_extend import _05_merge as merge
from topo_tools.core.edge_extend import attempt
from topo_tools.core.edge_match._constants import PASSTHROUGH_PARENT_FID

logger = getLogger(__name__)


def list_groups(conn: DuckDBPyConnection, name: str) -> list[int]:
    """Distinct assigned parent fids, ascending: deterministic iteration order."""
    rows = conn.execute(f"""--sql
        SELECT DISTINCT parent_fid FROM "{name}_02_assign" ORDER BY parent_fid
    """).fetchall()
    return [row[0] for row in rows]


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None,
    debug: bool = False,
    carry_columns: list[str] | None = None,
    child_columns: list[str] | None = None,
    passthrough: bool = False,
) -> None:
    """Loop over all groups sequentially, each isolated in its own subprocess.

    With passthrough=True and any zero-overlap children present, one extra
    orphan group is run afterward, tagged with PASSTHROUGH_PARENT_FID.
    """
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_03b" AS
        SELECT NULL::BIGINT AS child_fid, NULL::BIGINT AS parent_fid,
               NULL::VARCHAR AS reason, NULL::VARCHAR AS source_file,
               NULL::GEOMETRY AS geom
        WHERE FALSE
    """)

    carry_sql = "".join(f', a."{c}" AS "{c}"' for c in (carry_columns or []))
    child_select_cols = (
        ", ".join(f'c."{c}"' for c in child_columns)
        if child_columns is not None
        else "c.*"
    )
    for parent_fid in list_groups(conn, name):
        child_select_sql = f"""--sql
            SELECT {child_select_cols}{carry_sql}
            FROM "{name}_child_01" c
            JOIN "{name}_02_assign" a ON a.child_fid = c.fid
            WHERE a.parent_fid = {parent_fid}
        """
        fids_sql = (
            f'SELECT child_fid FROM "{name}_02_assign" WHERE parent_fid = {parent_fid}'
        )
        _run_group(
            conn,
            name,
            tmp_dir,
            parent_fid,
            child_select_sql,
            fids_sql,
            threads=threads,
            debug=debug,
        )

    if passthrough:
        orphan_count = conn.execute(
            f'SELECT COUNT(*) FROM "{name}_02_unassigned"'
        ).fetchone()[0]
        if orphan_count:
            child_select_sql = f"""--sql
                SELECT {child_select_cols} FROM "{name}_child_01" c
                WHERE c.fid IN (SELECT child_fid FROM "{name}_02_unassigned")
            """
            fids_sql = f'SELECT child_fid FROM "{name}_02_unassigned"'
            _run_group(
                conn,
                name,
                tmp_dir,
                PASSTHROUGH_PARENT_FID,
                child_select_sql,
                fids_sql,
                threads=threads,
                debug=debug,
            )

    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [f"{name}_03a"]
    ).fetchone()
    if exists is None:
        msg = f"match: no group produced any output for {name}"
        raise RuntimeError(msg)


def _run_group(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    parent_fid: int,
    child_select_sql: str,
    fids_sql: str,
    *,
    threads: int | None,
    debug: bool,
) -> None:
    """Export one group's children, extend them in an isolated subprocess."""
    gname = f"{name}_g{parent_fid}"
    group_dir = tmp_dir / gname
    group_dir.mkdir(parents=True, exist_ok=True)

    conn.execute(f"""--sql
        COPY ({child_select_sql}) TO '{group_dir / "child.parquet"}' (FORMAT PARQUET)
    """)

    # spawn re-imports from scratch (no logging config); the worker puts an
    # error string (or None) on the queue so a raised exception surfaces here.
    exitcode, err = spawn_worker(_group_worker, (group_dir, threads, debug))
    output_path = group_dir / "output.parquet"
    if exitcode != 0 or err or not output_path.exists():
        logger.error(
            "match: group parent_fid=%s failed, dropping its children from "
            "the output. exitcode=%s error=%s (see %s for exported inputs)",
            parent_fid,
            exitcode,
            err,
            group_dir,
        )
        reason = err or f"worker exited with no output (exitcode={exitcode})"
        _record_dropped_group(conn, name, parent_fid, reason, fids_sql)
        return

    _append_to_reassembly(conn, name, parent_fid, output_path)

    if not debug:
        shutil.rmtree(group_dir, ignore_errors=True)


def _append_to_reassembly(
    conn: DuckDBPyConnection, name: str, parent_fid: int, output_path: Path
) -> None:
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [f"{name}_03a"]
    ).fetchone()
    # Parquet round-trips an untagged geom column as 'OGC:CRS84'; re-tag to
    # match this table's own schema before INSERT INTO can accept it.
    if exists is None:
        conn.execute(f"""--sql
            CREATE TABLE "{name}_03a" AS
            SELECT * EXCLUDE (geom), ST_SetCRS(geom, 'EPSG:4326') AS geom,
                   {parent_fid} AS parent_fid
            FROM read_parquet('{output_path}')
        """)
    else:
        conn.execute(f"""--sql
            INSERT INTO "{name}_03a" BY NAME
            SELECT * EXCLUDE (geom), ST_SetCRS(geom, 'EPSG:4326') AS geom,
                   {parent_fid} AS parent_fid
            FROM read_parquet('{output_path}')
        """)


def _record_dropped_group(
    conn: DuckDBPyConnection, name: str, parent_fid: int, reason: str, fids_sql: str
) -> None:
    """Record every child of a failed group into `{name}_03b` for the issues report."""
    conn.execute(
        f"""--sql
            INSERT INTO "{name}_03b"
            SELECT fid AS child_fid, ? AS parent_fid, ? AS reason, source_file, geom
            FROM "{name}_child_01"
            WHERE fid IN ({fids_sql})
        """,
        [parent_fid, reason],
    )


def _group_worker(
    group_dir: Path,
    threads: int | None,
    debug: bool,  # noqa: FBT001
    result_queue: multiprocessing.Queue,
) -> None:
    """Child-process entry point; must stay module-level for spawn picklability.

    A freshly-spawned process has no logging config of its own, so under
    --debug this sets it up locally and tees to a per-group log file.
    """
    if debug:
        basicConfig(
            level=INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    with (
        worker_result(result_queue),
        log_file("group", group_dir) if debug else contextlib.nullcontext(),
    ):
        conn = get_connection("group", group_dir, threads=threads, debug=debug)
        conn.execute(f"""--sql
            CREATE TABLE "group_01" AS
            SELECT * FROM read_parquet('{group_dir / "child.parquet"}')
        """)  # already reprojected/coverage-cleaned by match's own inputs stage

        lines.main(conn, "group")
        attempt.main(conn, "group", debug=debug)
        merge.main(conn, "group", debug=debug)  # -> "group_05"

        # Same self-check a standalone edge-extend call runs in _06_outputs.py.
        check_no_erosion(conn, "group_01", "group_05")
        check_valid_topology(conn, "group_05", gap_maximum_width=0)

        conn.execute(f"""--sql
            COPY (SELECT * FROM "group_05")
            TO '{group_dir / "output.parquet"}' (FORMAT PARQUET)
        """)
        conn.close()
