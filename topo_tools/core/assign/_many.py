"""Assigns each child polygon to the parent it shares the largest area with."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import EQUAL_AREA_CRS
from topo_tools.core.duckdb_utils import bbox_columns_sql

logger = getLogger(__name__)


def assign_many(conn: DuckDBPyConnection, name: str) -> None:
    """Assign each child to its plurality-overlap parent; drop and log the rest.

    Each child decides independently, so one file's children MAY scatter
    across many different parents, correct for raw/unextended geometry,
    where overshoot can't misassign anything.
    """
    # Bbox columns precomputed here, not called inline in the join below:
    # DuckDB re-evaluates an inline envelope call per comparison, not once per row.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_tmp1" AS
        WITH parts AS (
            SELECT fid, UNNEST(ST_Dump(geom)).geom AS part_geom FROM "{name}_child_01"
        )
        SELECT fid, part_geom, {bbox_columns_sql("part_geom")}
        FROM parts
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_tmp2" AS
        WITH parts AS (
            SELECT fid, UNNEST(ST_Dump(geom)).geom AS part_geom FROM "{name}_parent_01"
        )
        SELECT fid, part_geom, {bbox_columns_sql("part_geom")}
        FROM parts
    """)

    # Shared area per (child, parent) fid pair, summed across all part-pairs:
    # a multi-part child can overlap a multi-part parent in more than one
    # place. Ranked in an equal-area CRS; only the intersection geometry (not
    # the whole layer) is transformed, to bound the cost.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_pairs" AS
        SELECT c.fid AS child_fid, p.fid AS parent_fid,
               SUM(ST_Area(ST_Transform(
                   ST_Intersection(c.part_geom, p.part_geom),
                   'EPSG:4326', '{EQUAL_AREA_CRS}'
               ))) AS shared_area
        FROM "{name}_02_tmp1" c
        JOIN "{name}_02_tmp2" p
          ON p.xmax >= c.xmin
         AND p.xmin <= c.xmax
         AND p.ymax >= c.ymin
         AND p.ymin <= c.ymax
         AND ST_Intersects(c.part_geom, p.part_geom)
        GROUP BY c.fid, p.fid
    """)

    # Plurality pick per child, ties broken by lowest parent fid.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_assign" AS
        SELECT child_fid, parent_fid FROM (
            SELECT child_fid, parent_fid,
                   ROW_NUMBER() OVER (
                       PARTITION BY child_fid ORDER BY shared_area DESC, parent_fid ASC
                   ) AS rn
            FROM "{name}_02_pairs"
            WHERE shared_area > 0
        ) WHERE rn = 1
    """)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_unassigned" AS
        SELECT fid AS child_fid, geom FROM "{name}_child_01"
        WHERE fid NOT IN (SELECT child_fid FROM "{name}_02_assign")
    """)

    unassigned = conn.execute(
        f'SELECT child_fid FROM "{name}_02_unassigned" ORDER BY child_fid'
    ).fetchall()
    if unassigned:
        fids = [row[0] for row in unassigned]
        logger.warning(
            "assign-many: dropping %d unmatched child fid(s) with no parent "
            "overlap: %s",
            len(fids),
            fids,
        )

    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp1"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp2"')
