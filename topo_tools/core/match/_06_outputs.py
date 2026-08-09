"""Validates topology and exports the matched output."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_gaps, check_overlaps
from topo_tools.core.io import export_geometry_table


def _build_issues(conn: DuckDBPyConnection, name: str) -> None:
    """Build `{name}_06`: every unassigned child plus every dropped-group child."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_06" AS
        SELECT 'unassigned-' || child_fid AS key, 'unassigned' AS kind,
               child_fid, NULL::BIGINT AS parent_fid, NULL::VARCHAR AS reason, geom
        FROM "{name}_02_unassigned"
        UNION ALL
        SELECT 'dropped_group-' || child_fid AS key, 'dropped_group' AS kind,
               child_fid, parent_fid, reason, geom
        FROM "{name}_03b"
    """)


def main(
    conn: DuckDBPyConnection,
    name: str,
    dest: Path,
    issues_dest: Path,
    *,
    debug: bool = False,
) -> None:
    """Output the matched layer + issues report to dest/issues_dest."""
    check_overlaps(conn, f"{name}_05")
    check_gaps(conn, f"{name}_05")

    _build_issues(conn, name)

    export_geometry_table(conn, f"{name}_05", dest)
    export_geometry_table(conn, f"{name}_06", issues_dest, exclude_fid=False)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03b"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_06"')
