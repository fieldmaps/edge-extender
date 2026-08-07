"""Validates topology and exports the matched output."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_gaps, check_overlaps
from topo_tools.core.io import export_geometry_table


def _build_issues(conn: DuckDBPyConnection, name: str) -> None:
    """Build `{name}_05`: every unassigned child plus every dropped-group child."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_05" AS
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
    """Output the matched layer + issues report to dest/issues_dest.

    check_gaps can't distinguish a gap match's clip introduced from a gap the
    parent/clip layer already had between two different parents' territories
    (e.g. a world ADM0 layer with disputed/unclaimed areas) -- ship as-is:
    a gap here is a real signal the clip layer itself needs extend treatment
    first, not something match should silently paper over.
    """
    check_overlaps(conn, f"{name}_04")
    check_gaps(conn, f"{name}_04")

    _build_issues(conn, name)

    export_geometry_table(conn, f"{name}_04", dest)
    export_geometry_table(conn, f"{name}_05", issues_dest, exclude_fid=False)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03b"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
