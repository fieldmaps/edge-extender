"""Unions original polygons with Voronoi extensions, then coverage-cleans seams."""

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import coverage_clean
from topo_tools.core.duckdb_utils import bbox_columns_sql


def main(conn: DuckDBPyConnection, name: str, *, debug: bool = False) -> None:
    """Merge original geometry with Voronoi extensions, then coverage-clean seams."""
    # Per-part _01 with bbox cols: a whole-fid bbox can span disjoint parts
    # and match nearly everything, so bbox tightness needs per-part granularity.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_05_tmp1" AS
        WITH parts AS (
            SELECT fid, UNNEST(ST_Dump(geom)).geom AS part_geom FROM "{name}_01"
        )
        SELECT fid, part_geom, {bbox_columns_sql("part_geom")}
        FROM parts
    """)

    # Bbox-prefiltered self-join per fid against nearby _01 parts only, never
    # one global ST_Union_Agg(_01) blob as the per-fid ST_Difference operand.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_05_tmp2" AS
        WITH
        v AS (
            SELECT fid, geom, {bbox_columns_sql("geom")}
            FROM "{name}_04"
        ),
        neighbor_union AS (
            SELECT v.fid AS vfid, ST_Union_Agg(p.part_geom) AS geom
            FROM v
            JOIN "{name}_05_tmp1" p
              ON p.xmax >= v.xmin AND p.xmin <= v.xmax
             AND p.ymax >= v.ymin AND p.ymin <= v.ymax
             AND ST_Intersects(p.part_geom, v.geom)
            GROUP BY v.fid
        ),
        snapped AS (
            SELECT v.fid,
                CASE WHEN n.geom IS NOT NULL
                    THEN ST_Snap(v.geom, n.geom, {SNAP_TOLERANCE})
                    ELSE v.geom
                END AS geom,
                n.geom AS neighbor_geom
            FROM v
            LEFT JOIN neighbor_union n ON v.fid = n.vfid
        ),
        remainder AS (
            SELECT fid,
                ST_MakeValid(ST_CollectionExtract(
                    CASE WHEN neighbor_geom IS NOT NULL
                        THEN ST_Difference(geom, neighbor_geom)
                        ELSE geom
                    END, 3
                )) AS geom
            FROM snapped
        )
        SELECT fid, geom FROM "{name}_01"
        UNION ALL
        SELECT fid, geom FROM remainder WHERE NOT ST_IsEmpty(geom)
    """)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05_tmp1"')

    # Dissolve to one row per fid, reattach original attribute columns.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_05_tmp3" AS
        SELECT o.* EXCLUDE (geom), d.geom
        FROM (
            SELECT fid, ST_Union_Agg(geom) AS geom
            FROM "{name}_05_tmp2"
            GROUP BY fid
        ) d
        JOIN "{name}_01" o USING (fid)
    """)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05_tmp2"')

    # Closes floating-point seams from the per-fid ST_Difference calls above;
    # every point here belongs to exactly one fid, so any find is seam noise, not a gap.
    coverage_clean(conn, f"{name}_05_tmp3", f"{name}_05", fids=None)
