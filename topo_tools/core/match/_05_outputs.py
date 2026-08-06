"""Validates topology and exports the matched output."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_gaps, check_overlaps
from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Output results to dest.

    check_gaps can't distinguish a gap match's clip introduced from a gap the
    parent/clip layer already had between two different parents' territories
    (e.g. a world ADM0 layer with disputed/unclaimed areas) -- ship as-is:
    a gap here is a real signal the clip layer itself needs extend treatment
    first, not something match should silently paper over.
    """
    check_overlaps(conn, f"{name}_04")
    check_gaps(conn, f"{name}_04")

    export_geometry_table(conn, f"{name}_04", dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
