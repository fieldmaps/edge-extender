"""Validates topology and exports output files from the stitched geometry table."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import check_invalid_edges, gap_geometries_sql
from topo_tools.core.io import export_geometry_table, export_issues_table
from topo_tools.core.units import METERS_PER_DEGREE, m2_per_deg2_factor

logger = getLogger(__name__)


def _build_issues(conn: DuckDBPyConnection, name: str) -> None:
    """Build `{name}_03`: gaps wider than the noise floor left after coverage-clean."""
    table = f"{name}_02"
    m2_per_deg2 = m2_per_deg2_factor(conn, table)
    width_m = f"(ST_MaximumInscribedCircle(geom)).radius * 2 * {METERS_PER_DEGREE}"
    thinness_ratio = "4 * pi() * ST_Area(geom) / POWER(ST_Perimeter(geom), 2)"
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_03" AS
        SELECT 'gap-' || row_number() OVER () AS key, 'gap' AS kind,
               ST_Area(geom) * {m2_per_deg2} AS area_m2, {width_m} AS max_width_m,
               {thinness_ratio} AS thinness_ratio,
               NULL::BIGINT AS unit_a, NULL::BIGINT AS unit_b,
               NULL::BIGINT AS parent_fid, NULL::VARCHAR AS reason,
               NULL::DOUBLE AS unit_a_area_change_m2,
               NULL::DOUBLE AS unit_b_area_change_m2,
               NULL::DOUBLE AS filled_area_m2, FALSE AS fixed,
               NULL::VARCHAR AS source_file, geom
        FROM {gap_geometries_sql(table)}
        WHERE (ST_MaximumInscribedCircle(geom)).radius * 2 > {SNAP_TOLERANCE}
    """)


def main(
    conn: DuckDBPyConnection,
    name: str,
    dest: Path,
    issues_dest: Path,
    *,
    debug: bool = False,
) -> None:
    """Output the stitched layer + issues report to dest/issues_dest."""
    check_invalid_edges(conn, f"{name}_02")

    _build_issues(conn, name)

    remaining = conn.execute(f"""--sql
        SELECT COUNT(*) FROM "{name}_03" WHERE kind = 'gap'
    """).fetchall()[0][0]
    if remaining:
        logger.warning(
            "stitch: %d gap(s) wider than the noise floor remain in the output "
            "(may be a legitimate unfilled gap, not a defect), see the issues file",
            remaining,
        )

    export_geometry_table(conn, f"{name}_02", dest)
    export_issues_table(conn, f"{name}_03", issues_dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
