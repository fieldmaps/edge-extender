"""Fixes gap/overlap defects with ST_CoverageClean, escalating gap_maximum_width."""

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


def _defect_unrelated_fid_outcomes(
    conn: DuckDBPyConnection, name: str, table_in: str, table_out: str
) -> tuple[int, int]:
    """Return (collapsed, drifted) counts for fids untouched by any detected defect.

    Defect-adjacent fids are exempt from both checks.
    """
    return conn.execute(f"""--sql
        WITH defect_adjacent AS (
            SELECT unit_a AS fid FROM "{name}_02" WHERE kind = 'overlap'
            UNION
            SELECT unit_b AS fid FROM "{name}_02" WHERE kind = 'overlap'
            UNION
            SELECT DISTINCT i.fid
            FROM "{table_in}" i, "{name}_02" g
            WHERE g.kind = 'gap' AND ST_Intersects(i.geom, g.geom)
        )
        SELECT
            COUNT(*) FILTER (WHERE ST_IsEmpty(o.geom) AND i.area > 0),
            COUNT(*) FILTER (WHERE NOT ST_IsEmpty(o.geom) AND o.area != i.area)
        FROM (SELECT fid, ST_Area(geom) AS area FROM "{table_in}") i
        JOIN (SELECT fid, geom, ST_Area(geom) AS area FROM "{table_out}") o USING (fid)
        WHERE i.fid NOT IN (SELECT fid FROM defect_adjacent)
    """).fetchall()[0]


def _bad_geometry_type_count(conn: DuckDBPyConnection, table: str) -> int:
    """Count fids whose fixed geometry isn't Polygon/MultiPolygon."""
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
    # has_coverage_violations() never detects gaps.
    if not has_coverage_violations(conn, table) and base_gap_maximum_width_deg is None:
        conn.execute(
            f'CREATE OR REPLACE TABLE "{out_table}" AS SELECT * FROM "{table}"'
        )
        return

    snap_mode, snap_value = snapping_distance
    snapping_distance_deg = None if snap_mode == "auto" else snap_value
    input_area = _total_area(conn, table)
    min_area = input_area * AREA_SANITY_FACTOR

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
        collapsed, drifted = _defect_unrelated_fid_outcomes(
            conn, name, table, out_table
        )
        bad_types = _bad_geometry_type_count(conn, out_table)
        if (
            not has_coverage_violations(conn, out_table)
            and output_area >= min_area
            and collapsed == 0
            and bad_types == 0
        ):
            if drifted:
                logger.warning(
                    "clean: %d fid(s) with no connection to any detected gap/overlap "
                    "shifted area anyway (ST_CoverageClean's global renoding) on %s",
                    drifted,
                    table,
                )
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
            f"invalid or collapsed output (area {output_area} vs input {input_area}, "
            f"{collapsed} fid(s) with no detected defect collapsed to empty, "
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
