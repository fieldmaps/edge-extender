"""Validates topology and exports the mosaicked output."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import (
    assign_issue_rows_sql,
    check_valid_topology,
    gap_issues_sql,
)
from topo_tools.core.io import export_geometry_table, export_issues_table

logger = getLogger(__name__)

_ISSUE_COLUMNS = """
    NULL::DOUBLE AS area_m2, NULL::DOUBLE AS max_width_m,
    NULL::DOUBLE AS thinness_ratio, NULL::BIGINT AS unit_b,
    NULL::DOUBLE AS unit_a_area_change_m2, NULL::DOUBLE AS unit_b_area_change_m2,
    NULL::DOUBLE AS filled_area_m2, FALSE AS fixed
"""


def _build_issues(
    conn: DuckDBPyConnection, name: str, *, code_join: bool = False
) -> None:
    """Build `{name}_05`: every unassigned child, plus non-noise gaps."""
    table = f"{name}_04"
    parts = [
        f"""
        SELECT 'unassigned-' || child_fid AS key, 'unassigned' AS kind,
               child_fid AS unit_a, NULL::BIGINT AS parent_fid,
               NULL::VARCHAR AS reason, {_ISSUE_COLUMNS}, source_file, geom
        FROM "{name}_02_unassigned"
        """,
        gap_issues_sql(conn, table),
    ]
    if code_join:
        parts.append(assign_issue_rows_sql(name, source_file_expr="c.source_file"))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_05" AS
        {" UNION ALL BY NAME ".join(parts)}
    """)


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    dest: Path,
    issues_dest: Path,
    *,
    code_join: bool = False,
    debug: bool = False,
) -> None:
    """Output the mosaicked layer + issues report to dest/issues_dest."""
    check_valid_topology(conn, f"{name}_04")

    _build_issues(conn, name, code_join=code_join)

    remaining = conn.execute(f"""--sql
        SELECT COUNT(*) FROM "{name}_05" WHERE kind = 'gap'
    """).fetchall()[0][0]
    if remaining:
        logger.warning(
            "mosaic: %d gap(s) wider than the noise floor remain in the output "
            "(may be a legitimate hole in the parent layer, not a defect), "
            "see the issues file",
            remaining,
        )

    export_geometry_table(conn, f"{name}_04", dest)
    export_issues_table(conn, f"{name}_05", issues_dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
