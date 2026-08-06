"""Fixes gap/overlap defects with ST_CoverageClean.

Overlaps are always fixed unconditionally by ST_CoverageClean itself -- no
flag controls that. gap_maximum_width and snapping_distance are the only
tunables, both taken directly in decimal degrees (the units `_01` is
already stored in, EPSG:4326) -- no meters conversion, matching GDAL/OGR's
convention that a distance parameter on an unprojected layer is in the
layer's native units, not meters. See `docs/clean.md`.

gap_maximum_width additionally has two confirmed real failure modes:

1. ST_CoverageClean can leave residual invalid edges (or raise a
   TopologyException outright) at certain widths, entirely unrelated to
   snapping_distance, in a narrow and non-monotonic way -- verified against
   a real admin-boundary defect.
2. At single-digit-degrees-and-up widths, ST_CoverageClean can silently
   erode or entirely erase real polygon area, not just close gaps -- also
   verified against real data. A large "just make it big enough to fill
   everything" constant is therefore not a safe design; there is no width
   that's both "definitely wide enough" and "definitely safe."

`main()` retries the resolved target width through
`GAP_WIDTH_ESCALATION_FACTORS`, validating each attempt against
has_coverage_violations(), a total-area sanity floor (AREA_SANITY_FACTOR --
has_coverage_violations() alone passes a totally empty result as "no
violations"), a per-fid erosion check, and a geometry-type check. The per-fid check
exempts any fid touching a filled gap or party to a detected overlap --
ST_CoverageClean can legitimately redraw that fid's whole neighborhood, not
just the immediate defect -- and requires every other fid (no connection to
any detected defect) to come out essentially unchanged. This catches a
small, otherwise-uninvolved feature collapsing even when the dataset's
total area still clears the sanity floor. The geometry-type check rejects any fid whose
fixed geometry is not a Polygon/MultiPolygon, since ST_Area() silently sums
only the polygonal parts of a mixed GeometryCollection and would otherwise
let a fid partly reduced to a stray line or point pass as area-preserving.
Both are confirmed real failure shapes, distinct from the total-collapse
case: several unrelated polygons collapsed to zero area in one combined
call even though each was fine processed alone. Escalation only ever widens
(never narrows) the target, so auto/all/explicit semantics are preserved.
See docs/clean.md.
"""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import coverage_clean, has_coverage_violations

from ._constants import (
    ALL_GAP_WIDTH_EPSILON_FACTOR,
    AREA_SANITY_FACTOR,
    DEFAULT_THINNESS_RATIO,
    GAP_WIDTH_ESCALATION_FACTORS,
)

logger = getLogger(__name__)


def _resolve_gap_maximum_width_deg(
    conn: DuckDBPyConnection,
    name: str,
    gap_maximum_width: tuple[str, float | None],
) -> float | None:
    mode, value = gap_maximum_width
    if mode in ("auto", "all"):
        where = "kind = 'gap'"
        if mode == "auto":
            where += f" AND thinness_ratio <= {DEFAULT_THINNESS_RATIO}"
        widest_deg = conn.execute(f"""--sql
            SELECT MAX((ST_MaximumInscribedCircle(geom)).radius * 2)
            FROM "{name}_02" WHERE {where}
        """).fetchall()[0][0]
        if widest_deg is None:
            return None
        return widest_deg * ALL_GAP_WIDTH_EPSILON_FACTOR
    return value


def _total_area(conn: DuckDBPyConnection, table: str) -> float:
    return (
        conn.execute(f'SELECT SUM(ST_Area(geom)) FROM "{table}"').fetchall()[0][0]
        or 0.0
    )


def _eroded_fid_count(
    conn: DuckDBPyConnection, name: str, table_in: str, table_out: str
) -> int:
    """Count fids that shrank with no detected defect of their own to explain it.

    A fid touching a gap that gets filled, or a party to a detected overlap,
    can legitimately lose (or gain) a large share of its own area --
    ST_CoverageClean redraws the whole neighborhood around a fix, not just
    the two features directly in conflict (confirmed: filling a gap can
    fully reassign an adjacent fid's area into a neighbor even though that
    fid was never itself part of any overlap). A fid with no connection to
    either kind of detected defect should come out essentially unchanged;
    any real loss there is erosion, not a side effect of a legitimate fix.
    """
    return conn.execute(f"""--sql
        WITH overlap_budget AS (
            SELECT fid, SUM(area) AS allowed_shrink
            FROM (
                SELECT unit_a AS fid, ST_Area(geom) AS area
                FROM "{name}_02" WHERE kind = 'overlap'
                UNION ALL
                SELECT unit_b AS fid, ST_Area(geom) AS area
                FROM "{name}_02" WHERE kind = 'overlap'
            )
            GROUP BY fid
        ),
        gap_adjacent AS (
            SELECT DISTINCT i.fid
            FROM "{table_in}" i, "{name}_02" g
            WHERE g.kind = 'gap' AND ST_Intersects(i.geom, g.geom)
        )
        SELECT COUNT(*)
        FROM (SELECT fid, ST_Area(geom) AS area FROM "{table_in}") i
        JOIN (SELECT fid, ST_Area(geom) AS area FROM "{table_out}") o USING (fid)
        LEFT JOIN overlap_budget b USING (fid)
        WHERE o.area < i.area - COALESCE(b.allowed_shrink, 0) - i.area * 1e-9
          AND i.fid NOT IN (SELECT fid FROM gap_adjacent)
    """).fetchall()[0][0]


def _bad_geometry_type_count(conn: DuckDBPyConnection, table: str) -> int:
    """Count rows whose geometry is not a Polygon or MultiPolygon.

    ST_Area() sums only the polygonal members of a mixed GeometryCollection,
    so a fid partly reduced to a stray line or point during the fix can
    still measure as area-preserving while being invalid output.
    """
    return conn.execute(f"""--sql
        SELECT COUNT(*) FROM "{table}"
        WHERE ST_GeometryType(geom) NOT IN ('POLYGON', 'MULTIPOLYGON')
    """).fetchall()[0][0]


def main(
    conn: DuckDBPyConnection,
    name: str,
    *,
    gap_maximum_width: tuple[str, float | None],
    snapping_distance: tuple[str, float | None],
) -> None:
    """Fix gap/overlap defects in `{name}_01`, writing `{name}_03`."""
    table = f"{name}_01"
    out_table = f"{name}_03"

    base_gap_maximum_width_deg = _resolve_gap_maximum_width_deg(
        conn, name, gap_maximum_width
    )
    # has_coverage_violations() only catches overlaps/mismatched edges, never
    # gaps (confirmed empirically: a valid edge-matched ring fully surrounding
    # a real hole returns False -- see docs/clean.md). A gap-only input with
    # nothing to escalate (base width is None, i.e. no gap qualifies to fill
    # under the resolved mode) is the only case with truly nothing to fix.
    if not has_coverage_violations(conn, table) and base_gap_maximum_width_deg is None:
        conn.execute(
            f'CREATE OR REPLACE TABLE "{out_table}" AS SELECT * FROM "{table}"'
        )
        return

    snap_mode, snap_value = snapping_distance
    snapping_distance_deg = None if snap_mode == "auto" else snap_value
    input_area = _total_area(conn, table)
    min_area = input_area * AREA_SANITY_FACTOR

    # Nothing to escalate when no gap qualifies for filling at all -- there's
    # no target width to widen.
    factors = (
        (1.0,) if base_gap_maximum_width_deg is None else GAP_WIDTH_ESCALATION_FACTORS
    )

    last_error: Exception | None = None
    for factor in factors:
        candidate_width = (
            None
            if base_gap_maximum_width_deg is None
            else base_gap_maximum_width_deg * factor
        )
        try:
            coverage_clean(
                conn,
                table,
                out_table,
                fids=None,
                gap_maximum_width=candidate_width,
                snapping_distance=snapping_distance_deg,
            )
        except Exception as e:  # noqa: BLE001 -- this rung failed, try the next one
            last_error = e
            continue
        output_area = _total_area(conn, out_table)
        eroded = _eroded_fid_count(conn, name, table, out_table)
        bad_types = _bad_geometry_type_count(conn, out_table)
        if (
            not has_coverage_violations(conn, out_table)
            and output_area >= min_area
            and eroded == 0
            and bad_types == 0
        ):
            pct_change = (
                (output_area - input_area) / input_area * 100 if input_area else 0.0
            )
            logger.info(
                "clean: total area %s %.4f%% (%.6f -> %.6f) on %s",
                "gained" if pct_change >= 0 else "lost",
                abs(pct_change),
                input_area,
                output_area,
                table,
            )
            if factor != factors[0]:
                logger.warning(
                    "coverage_clean needed gap_maximum_width escalated x%.3f "
                    "(%s -> %s) to resolve a coverage instability on %s",
                    factor,
                    base_gap_maximum_width_deg,
                    candidate_width,
                    table,
                )
            return
        last_error = RuntimeError(
            f"invalid or eroded output (area {output_area} vs input {input_area}, "
            f"{eroded} fid(s) eroded beyond their measured overlap exposure, "
            f"{bad_types} fid(s) with a non-polygon geometry type) at "
            f"gap_maximum_width={candidate_width}"
        )

    widest_tried = candidate_width
    msg = (
        f"gap_maximum_width escalation exhausted {len(factors)} attempts "
        f"({base_gap_maximum_width_deg} to {widest_tried}) without resolving a "
        f"coverage-clean instability on {table}. This is a dataset-specific "
        f"GEOS numerical edge case, not a parameter you can tune around -- "
        f"inspect with --debug, or consider filing it as a duckdb-spatial/GEOS "
        f"bug report."
    )
    raise RuntimeError(msg) from last_error
