"""Detects gap and overlap defects in a single polygon layer.

Detection only -- no geometry is modified here.

- Gaps: fully-enclosed holes in the whole-table union only; open inlets
  between non-enclosing polygons don't count.
- Overlaps: bbox-prefiltered pairwise join, whole-fid bboxes. Skipped
  entirely when `has_coverage_violations()` is already False.

Gap rows carry a Polsby-Popper thinness_ratio (NULL on overlap rows), used
by the clean stage's auto gap-fill mode. Each detection kind falls back to
an empty result (logged) on failure instead of raising.
"""

from collections.abc import Callable
from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import has_coverage_violations

from ._units import METERS_PER_DEGREE, m2_per_deg2_factor

logger = getLogger(__name__)


def _detect_or_empty(
    conn: DuckDBPyConnection,
    kind: str,
    source: str,
    empty_sql: str,
    build: Callable[[DuckDBPyConnection, str], None],
) -> None:
    """Call build(conn, source); on failure, log and run empty_sql instead.

    Ensures the target table always exists, so a failed kind doesn't crash
    main()'s UNION ALL with a missing table.
    """
    try:
        build(conn, source)
    except Exception as e:  # noqa: BLE001 -- GEOS topology failures surface as generic duckdb errors
        logger.warning(
            "%s detection failed on %s (%s); reporting none", kind, source, e
        )
        conn.execute(empty_sql)


def _build_gaps(conn: DuckDBPyConnection, tmp: str, table: str) -> None:
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{tmp}" AS
        WITH union_cte AS (
            SELECT ST_Union_Agg(geom) AS u FROM "{table}"
            WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
        ),
        parts AS (
            SELECT (UNNEST(ST_Dump(u))).geom AS poly FROM union_cte WHERE u IS NOT NULL
        ),
        holes AS (
            SELECT UNNEST(ST_Dump(
                ST_Difference(ST_MakePolygon(ST_ExteriorRing(poly)), poly)
            )).geom AS geom
            FROM parts WHERE ST_NumInteriorRings(poly) > 0
        )
        SELECT row_number() OVER () AS n, geom
        FROM holes
        WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
    """)


def _build_overlaps(conn: DuckDBPyConnection, tmp: str, table: str) -> None:
    # ST_Overlaps/ST_Contains, not ST_Intersects -- skips merely-touching
    # adjacent pairs; ST_Contains alone catches full containment.
    #
    # Projecting to (fid, geom) before the self-join avoids DuckDB's
    # single-threaded fallback on a wide table.
    narrow = f"{table}_narrow"
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{narrow}" AS SELECT fid, geom FROM "{table}"
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{tmp}" AS
        WITH pairs AS (
            SELECT a.fid AS unit_a, b.fid AS unit_b,
                   ST_MakeValid(
                       ST_CollectionExtract(ST_Intersection(a.geom, b.geom), 3)
                   ) AS geom
            FROM "{narrow}" a JOIN "{narrow}" b
              ON a.fid < b.fid
              AND ST_XMax(b.geom) >= ST_XMin(a.geom)
              AND ST_XMin(b.geom) <= ST_XMax(a.geom)
              AND ST_YMax(b.geom) >= ST_YMin(a.geom)
              AND ST_YMin(b.geom) <= ST_YMax(a.geom)
              AND (
                  ST_Overlaps(a.geom, b.geom)
                  OR ST_Contains(a.geom, b.geom)
                  OR ST_Contains(b.geom, a.geom)
              )
        )
        SELECT row_number() OVER () AS n, unit_a, unit_b, geom
        FROM pairs
        WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
    """)
    conn.execute(f'DROP TABLE IF EXISTS "{narrow}"')


def main(
    conn: DuckDBPyConnection,
    name: str,
    *,
    debug: bool = False,
) -> None:
    """Detect gap/overlap issues in `{name}_01`, writing `{name}_02`."""
    table = f"{name}_01"

    gaps_tmp = f"{name}_02_tmp1"
    overlaps_tmp = f"{name}_02_tmp2"

    _detect_or_empty(
        conn,
        "gap",
        table,
        f'CREATE OR REPLACE TABLE "{gaps_tmp}" AS '
        "SELECT NULL::BIGINT AS n, NULL::GEOMETRY AS geom WHERE FALSE",
        lambda c, t: _build_gaps(c, gaps_tmp, t),
    )
    empty_overlaps_sql = (
        f'CREATE OR REPLACE TABLE "{overlaps_tmp}" AS '
        "SELECT NULL::BIGINT AS n, NULL::BIGINT AS unit_a, "
        "NULL::BIGINT AS unit_b, NULL::GEOMETRY AS geom WHERE FALSE"
    )
    if has_coverage_violations(conn, table):
        _detect_or_empty(
            conn,
            "overlap",
            table,
            empty_overlaps_sql,
            lambda c, t: _build_overlaps(c, overlaps_tmp, t),
        )
    else:
        conn.execute(empty_overlaps_sql)
    # max_width_m skips the cos(lat) factor -- exact N-S, approximate E-W.
    m2_per_deg2 = m2_per_deg2_factor(conn, table)
    width_m = f"(ST_MaximumInscribedCircle(geom)).radius * 2 * {METERS_PER_DEGREE}"
    # Polsby-Popper thinness ratio, computed directly in raw degree-space.
    thinness_ratio = "4 * pi() * ST_Area(geom) / POWER(ST_Perimeter(geom), 2)"
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" AS
        SELECT 'gap-' || n AS key, 'gap' AS kind,
               ST_Area(geom) * {m2_per_deg2} AS area_m2,
               {width_m} AS max_width_m,
               {thinness_ratio} AS thinness_ratio,
               NULL::BIGINT AS unit_a, NULL::BIGINT AS unit_b, geom
        FROM "{gaps_tmp}"
        UNION ALL
        SELECT 'overlap-' || n AS key, 'overlap' AS kind,
               ST_Area(geom) * {m2_per_deg2} AS area_m2,
               {width_m} AS max_width_m,
               NULL::DOUBLE AS thinness_ratio,
               unit_a, unit_b, geom
        FROM "{overlaps_tmp}"
    """)

    if not debug:
        for tmp in (gaps_tmp, overlaps_tmp):
            conn.execute(f'DROP TABLE IF EXISTS "{tmp}"')
