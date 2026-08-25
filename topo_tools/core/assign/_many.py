"""Assigns each child polygon to the parent it shares the largest area with."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.assign._one import _carry_forward_columns
from topo_tools.core.constants import EQUAL_AREA_CRS
from topo_tools.core.duckdb_utils import bbox_columns_sql

logger = getLogger(__name__)


def assign_many(
    conn: DuckDBPyConnection,
    name: str,
    *,
    parent_match_column: str | None = None,
    child_match_column: str | None = None,
    carry_columns: list[str] | None = None,
) -> None:
    """Assign each child to its plurality-overlap parent; drop and log the rest."""
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
        CREATE OR REPLACE TABLE "{name}_02_tmp3" AS
        SELECT child_fid, parent_fid FROM (
            SELECT child_fid, parent_fid,
                   ROW_NUMBER() OVER (
                       PARTITION BY child_fid ORDER BY shared_area DESC, parent_fid ASC
                   ) AS rn
            FROM "{name}_02_pairs"
            WHERE shared_area > 0
        ) WHERE rn = 1
    """)

    if parent_match_column and child_match_column:
        # Code candidate per child, restricted to a parent it overlaps at
        # all (guards against a stale/wrong code pointing at an unrelated
        # parent); ties (a code shared by more than one parent) broken by
        # lowest parent fid.
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_tmp4" AS
            SELECT child_fid, parent_fid FROM (
                SELECT j.child_fid, j.parent_fid,
                       ROW_NUMBER() OVER (
                           PARTITION BY j.child_fid ORDER BY j.parent_fid ASC
                       ) AS rn
                FROM (
                    SELECT c.fid AS child_fid, p.fid AS parent_fid
                    FROM "{name}_child_01" c
                    JOIN "{name}_parent_01" p
                      ON c."{child_match_column}" = p."{parent_match_column}"
                ) j
                JOIN "{name}_02_pairs" pr
                  ON pr.child_fid = j.child_fid
                 AND pr.parent_fid = j.parent_fid
                 AND pr.shared_area > 0
            ) WHERE rn = 1
        """)
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_assign" AS
            SELECT
                child_fid,
                COALESCE(code.parent_fid, spatial.parent_fid) AS parent_fid,
                CASE WHEN code.parent_fid IS NOT NULL THEN 'code'
                     ELSE 'spatial_fallback' END AS assignment_method,
                CASE WHEN code.parent_fid IS NOT NULL
                     THEN code.parent_fid = spatial.parent_fid END AS spatial_agrees
            FROM "{name}_02_tmp4" code
            FULL OUTER JOIN "{name}_02_tmp3" spatial USING (child_fid)
        """)
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp4"')
    else:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_assign" AS
            SELECT * FROM "{name}_02_tmp3"
        """)
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_tmp3"')

    _carry_forward_columns(conn, name, carry_columns)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_unassigned" AS
        SELECT fid AS child_fid, source_file, geom FROM "{name}_child_01"
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
