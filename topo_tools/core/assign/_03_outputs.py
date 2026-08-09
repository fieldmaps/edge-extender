"""Exports the child-to-parent crosswalk and an issues report of unassigned children."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import export_geometry_table


def _build_issues(conn: DuckDBPyConnection, name: str) -> None:
    """Build `{name}_03_issues`: every child with no assigned parent."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_03_issues" AS
        SELECT 'unassigned-' || child_fid AS key, 'unassigned' AS kind, *
        FROM "{name}_02_unassigned"
    """)


def main(
    conn: DuckDBPyConnection,
    name: str,
    dest: Path,
    issues_dest: Path,
    *,
    debug: bool = False,
) -> None:
    """Export the child-to-parent crosswalk + issues report to dest/issues_dest.

    No coverage hard gate here: an unclipped crosswalk is expected to have
    overlapping/gapped child geometry; that's clip's and stitch's job.
    """
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_03" AS
        SELECT c.*, a.parent_fid
        FROM "{name}_child_01" c
        JOIN "{name}_02_assign" a ON a.child_fid = c.fid
    """)

    _build_issues(conn, name)

    export_geometry_table(conn, f"{name}_03", dest, exclude_fid=False)
    export_geometry_table(conn, f"{name}_03_issues", issues_dest, exclude_fid=False)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03_issues"')
