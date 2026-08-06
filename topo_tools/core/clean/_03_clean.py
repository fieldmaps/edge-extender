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
`GAP_WIDTH_ESCALATION_FACTORS`, validating each attempt against both
has_coverage_violations() and a total-area sanity floor (AREA_SANITY_FACTOR
-- has_coverage_violations() alone passes a totally empty result as "no
violations"), and only ever widens (never narrows) the target, so
auto/all/explicit semantics are preserved. See docs/clean.md.
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
        if not has_coverage_violations(conn, out_table) and output_area >= min_area:
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
            f"invalid or eroded output (area {output_area} vs input {input_area}) "
            f"at gap_maximum_width={candidate_width}"
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
