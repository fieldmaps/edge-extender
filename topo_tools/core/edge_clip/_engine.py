"""Clips every row to its own parent_fid's geometry, isolated per distinct parent."""

import contextlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from duckdb import DuckDBPyConnection

from topo_tools.core.duckdb_utils import (
    bbox_columns_sql,
    get_connection,
    log_file,
    spawn_worker,
    worker_result,
)

from ._tiling import subdivide_boundary

if TYPE_CHECKING:
    import multiprocessing


def main(  # noqa: PLR0913 (each param is a distinct required input)
    conn: DuckDBPyConnection,
    table_in: str,
    parent_source: str,
    table_out: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
) -> None:
    """Clip every row of table_in to its own parent_fid's geometry, dropping empties.

    table_in MUST already carry a parent_fid column (assign's own output
    contract). Every distinct parent_fid is clipped in its own spawned
    subprocess, its boundary adaptively grid-tiled first; the first failed
    parent_fid raises immediately, aborting the whole run.
    """
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{table_out}" AS
        SELECT * EXCLUDE (parent_fid) FROM "{table_in}" WHERE FALSE
    """)
    parent_fids = [
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT parent_fid FROM "{table_in}" ORDER BY parent_fid'
        ).fetchall()
    ]

    for parent_fid in parent_fids:
        group_dir = tmp_dir / f"{table_out}_p{parent_fid}"
        # Always clear first: a stale group_dir from an earlier children
        # file reusing this parent_fid under --debug would collide on create.
        shutil.rmtree(group_dir, ignore_errors=True)
        group_dir.mkdir(parents=True, exist_ok=True)

        conn.execute(f"""--sql
            COPY (
                SELECT * EXCLUDE (parent_fid) FROM "{table_in}"
                WHERE parent_fid = {parent_fid}
            ) TO '{group_dir / "child.parquet"}' (FORMAT PARQUET)
        """)
        conn.execute(f"""--sql
            COPY (SELECT geom FROM {parent_source} WHERE fid = {parent_fid})
            TO '{group_dir / "parent.parquet"}' (FORMAT PARQUET)
        """)

        exitcode, err = spawn_worker(_clip_one_worker, (group_dir, threads, debug))
        output_path = group_dir / "output.parquet"
        if exitcode != 0 or err or not output_path.exists():
            msg = (
                f"clip: subprocess for parent_fid={parent_fid} failed "
                f"(exitcode={exitcode}, error={err}, see {group_dir} "
                "for exported inputs)"
            )
            raise RuntimeError(msg)

        conn.execute(f"""--sql
            INSERT INTO "{table_out}" BY NAME
            SELECT * FROM read_parquet('{output_path}')
        """)

        if not debug:
            shutil.rmtree(group_dir, ignore_errors=True)


def _clip_one_worker(
    group_dir: Path,
    threads: int | None,
    debug: bool,  # noqa: FBT001
    result_queue: "multiprocessing.Queue",
) -> None:
    """Child-process entry point; must stay module-level for spawn picklability."""
    with (
        worker_result(result_queue),
        log_file("clip", group_dir) if debug else contextlib.nullcontext(),
    ):
        worker_conn = get_connection("clip", group_dir, threads=threads, debug=debug)
        # Parquet round-trips an untagged column as 'OGC:CRS84', which
        # ST_Intersection then rejects against a sibling tagged 'EPSG:4326'.
        worker_conn.execute(f"""--sql
                CREATE TABLE clip_one AS
                SELECT ST_SetCRS(geom, 'EPSG:4326') AS geom
                FROM read_parquet('{group_dir / "parent.parquet"}')
            """)
        worker_conn.execute(f"""--sql
                CREATE TABLE clip_children AS
                SELECT * EXCLUDE (geom), ST_SetCRS(geom, 'EPSG:4326') AS geom,
                       {bbox_columns_sql("geom")}
                FROM read_parquet('{group_dir / "child.parquet"}')
            """)
        subdivide_boundary(worker_conn, "clip_one", "geom", "clip_btile_raw")
        # Bbox columns precomputed here, not called inline in the join below:
        # DuckDB re-evaluates an inline envelope call per comparison, not per row.
        worker_conn.execute(f"""--sql
                CREATE TABLE clip_btile AS
                SELECT geom, {bbox_columns_sql("geom")} FROM clip_btile_raw
            """)
        worker_conn.execute(f"""--sql
                COPY (
                    SELECT * FROM (
                        SELECT c.* EXCLUDE (geom, xmin, xmax, ymin, ymax),
                               ST_SetCRS(ST_Multi(ST_CollectionExtract(
                                   ST_Union_Agg(ST_Intersection(c.geom, b.geom)), 3
                               ))::GEOMETRY, 'EPSG:4326') AS geom
                        FROM clip_children c
                        JOIN clip_btile b
                          ON b.xmax >= c.xmin AND b.xmin <= c.xmax
                         AND b.ymax >= c.ymin AND b.ymin <= c.ymax
                        GROUP BY ALL
                    ) WHERE NOT ST_IsEmpty(geom)
                ) TO '{group_dir / "output.parquet"}' (FORMAT PARQUET)
            """)
        worker_conn.close()
