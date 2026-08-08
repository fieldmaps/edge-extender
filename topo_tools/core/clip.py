"""Clips a table of polygons to one or more parent boundaries via ST_Intersection.

mosaic's assign_table branch clips one parent fid at a time, each in its own
spawned OS process with that parent's boundary grid-tiled before
intersecting: plain ST_Intersection alone leaks GEOS's native heap across a
long-lived process, and one oversized parent can exceed available memory
even fully isolated.
"""

import contextlib
import math
import multiprocessing
import shutil
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import (
    CLIP_TILE_MAX_CELL,
    CLIP_TILE_MIN_CELL,
    CLIP_TILE_MIN_VERTICES,
    CLIP_TILE_TARGET_VERTICES,
)
from topo_tools.core.duckdb_utils import get_connection, log_file


def clip_to_parent(  # noqa: PLR0913 -- each param is a distinct required input
    conn: DuckDBPyConnection,
    table_in: str,
    parent_source: str,
    table_out: str,
    *,
    assign_table: str | None = None,
    tmp_dir: Path | None = None,
    threads: int | None = None,
    debug: bool = False,
) -> None:
    """Clip every row of table_in to its parent(s), dropping empty results.

    assign_table=None clips every row against one parent_source (match, itself
    already running inside a per-group subprocess -- no further isolation
    needed here). assign_table=<name> maps each row's fid to its own parent
    via that table (mosaic) and requires tmp_dir: each parent fid's clip runs
    in its own spawned subprocess, so the OS reclaims GEOS's native heap
    between parents.
    """
    if assign_table is None:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{table_out}" AS
            SELECT * FROM (
                SELECT t.* EXCLUDE (geom),
                       ST_Intersection(t.geom, p.geom) AS geom
                FROM "{table_in}" t, (SELECT geom FROM {parent_source}) p
            ) WHERE NOT ST_IsEmpty(geom)
        """)
        return

    if tmp_dir is None:
        msg = "tmp_dir is required when assign_table is given"
        raise ValueError(msg)

    _clip_by_parent_subprocess(
        conn,
        table_in,
        parent_source,
        table_out,
        assign_table,
        tmp_dir,
        threads=threads,
        debug=debug,
    )


def _clip_by_parent_subprocess(  # noqa: PLR0913, PLR0917 -- each param is a distinct required input
    conn: DuckDBPyConnection,
    table_in: str,
    parent_source: str,
    table_out: str,
    assign_table: str,
    tmp_dir: Path,
    *,
    threads: int | None,
    debug: bool,
) -> None:
    ctx = multiprocessing.get_context("spawn")

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{table_out}" AS
        SELECT * FROM "{table_in}" WHERE FALSE
    """)
    parent_fids = [
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT parent_fid FROM "{assign_table}" ORDER BY parent_fid'
        ).fetchall()
    ]

    for parent_fid in parent_fids:
        group_dir = tmp_dir / f"{table_out}_p{parent_fid}"
        group_dir.mkdir(parents=True, exist_ok=True)

        conn.execute(f"""--sql
            COPY (
                SELECT c.* FROM "{table_in}" c
                JOIN "{assign_table}" a
                  ON a.child_fid = c.fid AND a.parent_fid = {parent_fid}
            ) TO '{group_dir / "child.parquet"}' (FORMAT PARQUET)
        """)
        conn.execute(f"""--sql
            COPY (SELECT geom FROM {parent_source} WHERE fid = {parent_fid})
            TO '{group_dir / "parent.parquet"}' (FORMAT PARQUET)
        """)

        result_queue = ctx.Queue()
        process = ctx.Process(
            target=_clip_one_worker,
            args=(group_dir, threads, debug, result_queue),
        )
        process.start()
        process.join()

        err = (
            result_queue.get()
            if not result_queue.empty()
            else (
                f"worker exited with no result "
                f"(exitcode={process.exitcode}, likely killed/OOM)"
            )
        )
        output_path = group_dir / "output.parquet"
        if process.exitcode != 0 or err or not output_path.exists():
            msg = (
                f"mosaic: clip subprocess for parent_fid={parent_fid} failed "
                f"(exitcode={process.exitcode}, error={err}, see {group_dir} "
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
    try:
        with log_file("clip", group_dir) if debug else contextlib.nullcontext():
            worker_conn = get_connection(
                "clip", group_dir, threads=threads, debug=debug
            )
            # Parquet round-trips an untagged column as 'OGC:CRS84', which
            # ST_Intersection then rejects against a sibling tagged 'EPSG:4326'.
            worker_conn.execute(f"""--sql
                CREATE TABLE clip_one AS
                SELECT ST_SetCRS(geom, 'EPSG:4326') AS geom
                FROM read_parquet('{group_dir / "parent.parquet"}')
            """)
            worker_conn.execute(f"""--sql
                CREATE TABLE clip_children AS
                SELECT * EXCLUDE (geom), ST_SetCRS(geom, 'EPSG:4326') AS geom
                FROM read_parquet('{group_dir / "child.parquet"}')
            """)
            _subdivide_boundary(worker_conn)
            worker_conn.execute(f"""--sql
                COPY (
                    SELECT * FROM (
                        SELECT c.* EXCLUDE (geom),
                               ST_SetCRS(ST_Multi(ST_CollectionExtract(
                                   ST_Union_Agg(ST_Intersection(c.geom, b.geom)), 3
                               ))::GEOMETRY, 'EPSG:4326') AS geom
                        FROM clip_children c
                        JOIN clip_btile b
                          ON ST_XMax(b.geom) >= ST_XMin(c.geom)
                         AND ST_XMin(b.geom) <= ST_XMax(c.geom)
                         AND ST_YMax(b.geom) >= ST_YMin(c.geom)
                         AND ST_YMin(b.geom) <= ST_YMax(c.geom)
                        GROUP BY ALL
                    ) WHERE NOT ST_IsEmpty(geom)
                ) TO '{group_dir / "output.parquet"}' (FORMAT PARQUET)
            """)
            worker_conn.close()
        result_queue.put(None)
    except Exception as e:  # noqa: BLE001 -- must not raise across the process boundary uncaught
        result_queue.put(f"{type(e).__name__}: {e}")


def _adaptive_cell_size(vertex_count: int, width: float, height: float) -> float:
    """Solve a tile size from this parent's own vertex density, not a fixed constant.

    Calibrated so South Africa's real worst case (281k vertices, ADR-0016) lands
    at ~1 degree; sparser or simpler parents get coarser cells, denser ones finer.
    """
    bbox_area = max(width, 1e-9) * max(height, 1e-9)
    cell = math.sqrt(CLIP_TILE_TARGET_VERTICES * bbox_area / vertex_count)
    return min(max(cell, CLIP_TILE_MIN_CELL), CLIP_TILE_MAX_CELL)


def _subdivide_boundary(conn: DuckDBPyConnection) -> None:
    """Grid-subdivide clip_one's boundary into clip_btile, strip by strip.

    Mirrors fieldmaps/admin-boundaries' _03b_clip.py: shrinks each single
    ST_Intersection call's operand to a small lossless tile instead of the
    whole (possibly huge) parent boundary, bbox-joined rather than
    ST_Intersects (planned by DuckDB as a SPATIAL_JOIN, reserving ~1x RAM).
    Below CLIP_TILE_MIN_VERTICES, clips directly instead: too simple to need it.
    """
    x0, y0, x1, y1 = conn.execute(
        "SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) "
        "FROM clip_one"
    ).fetchone()
    vertex_count = (
        conn.execute("SELECT ST_NPoints(geom) FROM clip_one").fetchone()[0] or 0
    )

    if vertex_count < CLIP_TILE_MIN_VERTICES:
        conn.execute("CREATE TABLE clip_btile AS SELECT geom FROM clip_one")
        return

    cell = _adaptive_cell_size(vertex_count, x1 - x0, y1 - y0)
    ny = max(1, math.ceil((y1 - y0) / cell))

    occupied = [
        row[0]
        for row in conn.execute(
            f"""--sql
            WITH parts AS (SELECT (UNNEST(ST_Dump(geom))).geom AS g FROM clip_one)
            SELECT DISTINCT UNNEST(range(
                CAST(floor((ST_XMin(g) - {x0}) / {cell}) AS INTEGER),
                CAST(floor((ST_XMax(g) - {x0}) / {cell}) AS INTEGER) + 1
            )) AS i
            FROM parts ORDER BY i
            """
        ).fetchall()
    ]

    conn.execute("CREATE TABLE clip_btile (geom GEOMETRY)")
    for i in occupied:
        sx0, sx1 = x0 + i * cell, x0 + (i + 1) * cell
        sy0, sy1 = y0, y1
        conn.execute(f"""--sql
            INSERT INTO clip_btile
            WITH strip AS (
                SELECT ST_Intersection(
                    geom, ST_MakeEnvelope({sx0}, {sy0}, {sx1}, {sy1})
                ) AS g
                FROM clip_one
            ),
            gy AS (
                SELECT {sy0} + j * {cell} AS cy0,
                       {sy0} + (j + 1) * {cell} AS cy1
                FROM (SELECT UNNEST(range({ny})) AS j)
            )
            SELECT geom FROM (
                SELECT ST_Intersection(
                    strip.g, ST_MakeEnvelope({sx0}, gy.cy0, {sx1}, gy.cy1)
                ) AS geom
                FROM strip, gy
                WHERE NOT ST_IsEmpty(strip.g)
            ) WHERE NOT ST_IsEmpty(geom)
        """)
