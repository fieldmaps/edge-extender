"""Validates topology and exports the matched output."""

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
    NULL::DOUBLE AS filled_area_m2, FALSE AS fixed, NULL::VARCHAR AS source_file
"""


def _build_issues(
    conn: DuckDBPyConnection, name: str, *, code_join: bool = False
) -> None:
    """Build `{name}_06`: unassigned/dropped-group children, plus non-noise gaps."""
    table = f"{name}_05"
    parts = [
        f"""
        SELECT 'unassigned-' || child_fid AS key, 'unassigned' AS kind,
               child_fid AS unit_a, NULL::BIGINT AS parent_fid,
               NULL::VARCHAR AS reason, {_ISSUE_COLUMNS}, geom
        FROM "{name}_02_unassigned"
        """,
        f"""
        SELECT 'dropped_group-' || child_fid AS key, 'dropped_group' AS kind,
               child_fid AS unit_a, parent_fid, reason, {_ISSUE_COLUMNS}, geom
        FROM "{name}_03b"
        """,
        gap_issues_sql(conn, table),
    ]
    if code_join:
        parts.append(assign_issue_rows_sql(name))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_06" AS
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
    """Output the matched layer + issues report to dest/issues_dest."""
    check_valid_topology(conn, f"{name}_05")

    _build_issues(conn, name, code_join=code_join)

    remaining = conn.execute(f"""--sql
        SELECT COUNT(*) FROM "{name}_06" WHERE kind = 'gap'
    """).fetchall()[0][0]
    if remaining:
        logger.warning(
            "match: %d gap(s) wider than the noise floor remain in the output "
            "(may be a legitimate hole in the parent layer, not a defect), "
            "see the issues file",
            remaining,
        )

    export_geometry_table(conn, f"{name}_05", dest)
    export_issues_table(conn, f"{name}_06", issues_dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03b"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_06"')
