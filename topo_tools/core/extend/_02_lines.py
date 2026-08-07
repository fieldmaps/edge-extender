"""Extracts polygon boundary lines and retains per-polygon attributes."""

from duckdb import DuckDBPyConnection

from topo_tools.core.duckdb_utils import bbox_columns_sql


def main(conn: DuckDBPyConnection, name: str) -> None:
    """Create boundary lines from polygons."""
    # Per-polygon boundary lines, with bbox columns precomputed -- DuckDB
    # re-evaluates an inline envelope call per comparison, not once per row.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_tmp1" AS
        WITH boundary AS (
            SELECT fid, ST_Boundary(geom) AS geom FROM "{name}_01"
        )
        SELECT fid, geom, {bbox_columns_sql("geom")}
        FROM boundary
    """)

    # Per-polygon neighbor union, self-join with scalar bbox predicates plus
    # an exact ST_Intersects filter (no LATERAL); still plans as
    # PIECEWISE_MERGE_JOIN, not SPATIAL_JOIN.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_tmp2" AS
        SELECT a.fid AS afid, ST_Union_Agg(b.geom) AS neighbor_union
        FROM "{name}_02_tmp1" AS a
        JOIN "{name}_02_tmp1" AS b
          ON a.fid != b.fid
         AND b.xmax >= a.xmin
         AND b.xmin <= a.xmax
         AND b.ymax >= a.ymin
         AND b.ymin <= a.ymax
         AND ST_Intersects(a.geom, b.geom)
        GROUP BY a.fid
    """)

    # Exterior edges = each polygon's boundary minus its neighbour union.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" AS
        SELECT
            a.fid,
            UNNEST(ST_Dump(ST_LineMerge(ST_CollectionExtract(
                CASE WHEN n.neighbor_union IS NOT NULL
                    THEN ST_Difference(a.geom, n.neighbor_union)
                    ELSE a.geom
                END, 2
            )))).geom AS geom
        FROM "{name}_02_tmp1" AS a
        LEFT JOIN "{name}_02_tmp2" AS n ON a.fid = n.afid
    """)

    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp1"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp2"')
