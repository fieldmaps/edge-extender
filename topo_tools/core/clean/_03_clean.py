"""Fixes gap/overlap defects with ST_CoverageClean.

Overlaps are always fixed unconditionally by ST_CoverageClean itself -- no
flag controls that. gap_maximum_width and snapping_distance are the only
tunables.
"""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.extend._coverage import coverage_clean, has_coverage_violations

from ._02_issues import centroid_lat_of
from ._constants import (
    ALL_GAP_WIDTH_EPSILON_FACTOR,
    DEFAULT_THINNESS_RATIO,
    REDUCED_PRECISION_DEG,
)
from ._units import meters_to_degrees

logger = getLogger(__name__)


def _resolve_gap_maximum_width_deg(
    conn: DuckDBPyConnection,
    name: str,
    gap_maximum_width: tuple[str, float | None],
    centroid_lat: float,
) -> float | None:
    mode, value = gap_maximum_width
    if mode in ("auto", "all"):
        where = "kind = 'gap'"
        if mode == "auto":
            where += f" AND thinness_ratio <= {DEFAULT_THINNESS_RATIO}"
        widest_m = conn.execute(f"""--sql
            SELECT MAX(max_width_m) FROM "{name}_02" WHERE {where}
        """).fetchall()[0][0]
        if widest_m is None:
            return None
        return meters_to_degrees(widest_m * ALL_GAP_WIDTH_EPSILON_FACTOR, centroid_lat)
    return meters_to_degrees(value, centroid_lat)


def main(
    conn: DuckDBPyConnection,
    name: str,
    *,
    gap_maximum_width: tuple[str, float | None],
    snapping_distance: tuple[str, float | None],
    debug: bool = False,
) -> None:
    """Fix gap/overlap defects in `{name}_01`, writing `{name}_03`."""
    table = f"{name}_01"

    if not has_coverage_violations(conn, table):
        conn.execute(f'CREATE OR REPLACE TABLE "{name}_03" AS SELECT * FROM "{table}"')
        return

    centroid_lat = centroid_lat_of(conn, table)
    gap_maximum_width_deg = _resolve_gap_maximum_width_deg(
        conn, name, gap_maximum_width, centroid_lat
    )
    snap_mode, snap_value = snapping_distance
    snapping_distance_deg = (
        None if snap_mode == "auto" else meters_to_degrees(snap_value, centroid_lat)
    )

    try:
        coverage_clean(
            conn,
            table,
            f"{name}_03",
            None,
            gap_maximum_width_deg,
            snapping_distance_deg,
        )
    except Exception as e:  # noqa: BLE001 -- GEOS topology failures surface as generic duckdb errors
        logger.warning(
            "coverage_clean failed on %s (%s), retrying at reduced precision", table, e
        )
        reduced = f"{table}_reduced"
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{reduced}" AS
            SELECT * EXCLUDE (geom),
                   ST_ReducePrecision(geom, {REDUCED_PRECISION_DEG}) AS geom
            FROM "{table}"
        """)
        coverage_clean(
            conn,
            reduced,
            f"{name}_03",
            None,
            gap_maximum_width_deg,
            snapping_distance_deg,
        )
        if not debug:
            conn.execute(f'DROP TABLE IF EXISTS "{reduced}"')
