"""Detects gap and overlap defects in a single polygon layer.

Detection only -- no geometry is modified here. Ported from
topo-tools-js/src/lib/tools/topology-cleaner/pipeline/issues.ts:

- Gaps: interior rings of the whole-table union. Only catches fully-enclosed
  holes (a ring of polygons surrounding missing area) -- an open "inlet"
  between two non-enclosing polygons is not a gap by this definition (GEOS's
  own CoverageCleaner doc: "gaps which are not fully enclosed are not
  removed").
- Overlaps: bbox-prefiltered pairwise ST_Intersection, whole-fid bboxes (not
  per-part -- see core/extend/_02_lines.py's neighbor self-join for why
  per-part explosion regresses single-fid-many-parts datasets like Chile).
  The join predicate is ST_Overlaps/ST_Contains, not ST_Intersects -- see the
  note on `_build_overlaps` below.

Gap rows also carry a Polsby-Popper thinness ratio (4*pi*Area/Perimeter^2,
NULL on overlap rows) used by the clean stage's auto gap-fill mode.

Each of the two detection queries falls back to an empty result (logged) on
failure rather than raising -- one kind failing shouldn't block the other,
matching match's "failed group is logged and dropped, not fatal" precedent.

Gap detection always runs -- the whole-table union it needs is also the
only way to answer "are there any gaps at all," so there's no cheaper
substitute check to skip it with. Overlap detection is skipped (an empty
result written directly) when `has_coverage_violations()` is already False,
since that's equivalent to "the overlap self-join would find nothing" and
is far cheaper than actually running the O(n^2) self-join to confirm it.
"""

from collections.abc import Callable
from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import has_coverage_violations

from ._units import METERS_PER_DEGREE, cos_lat_factor

logger = getLogger(__name__)


def centroid_lat_of(conn: DuckDBPyConnection, table: str) -> float:
    lat = conn.execute(f"""--sql
        SELECT ST_Y(ST_Centroid(ST_Extent_Agg(geom))) FROM "{table}"
    """).fetchall()[0][0]
    return lat if lat is not None else 0.0


def _detect_or_empty(
    conn: DuckDBPyConnection,
    kind: str,
    source: str,
    empty_sql: str,
    build: Callable[[DuckDBPyConnection, str], None],
) -> None:
    """Call build(conn, source); on failure, log and fall back to an empty result.

    Executes `empty_sql` on failure so the target table this `build` call was
    supposed to create always exists afterward, instead of crashing the
    downstream UNION ALL in `main()` with a binder/catalog error.
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
    # ST_Intersects is true for any pair of polygons that merely share a
    # boundary edge -- the normal case for every adjacent pair in a coverage
    # layer, not a defect. At real admin-boundary scale (thousands of fids,
    # e.g. archipelago admin3 layers) that floods the join with candidates
    # whose ST_Intersection is a degenerate line/point, each still paying for
    # ST_Intersection + ST_MakeValid + ST_CollectionExtract. Confirmed on IDN
    # admin3 (7,069 fids): ST_Intersects matched 18,457 pairs and the stage
    # didn't finish in 6+ minutes. ST_Overlaps alone would miss a fully-
    # duplicated or nested polygon pair (its intersection equals both/one
    # input, so ST_Overlaps is false by OGC definition) -- ST_Contains in
    # both directions covers that case.
    #
    # Second, unrelated fix on the same query: self-joining `table` directly
    # (the real `_01` table, ~36 columns for real admin-boundary data) makes
    # DuckDB fall back to near-single-threaded execution even though only
    # fid/geom are referenced -- confirmed on IDN admin3: the join against
    # `_01` ran at ~99% CPU (7 min), the identical join against a `(fid,
    # geom)`-only projection of the same rows ran at ~420% CPU (102s). Always
    # project to a narrow staging table before the self-join.
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
    centroid_lat = centroid_lat_of(conn, table)
    cos_lat = cos_lat_factor(centroid_lat)

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
    # area_m2/max_width_m: area_deg2 * METERS_PER_DEGREE^2 * cos(centroid_lat) for
    # area; MIC diameter (deg) * METERS_PER_DEGREE (no cos factor -- matches
    # units.ts's degToM, exact for N-S widths, display-only approximation for E-W).
    m2_per_deg2 = METERS_PER_DEGREE**2 * cos_lat
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
