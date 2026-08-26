"""Validates topology and exports output files from the final merged geometry table."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_no_erosion, check_valid_topology
from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Output results to dest."""
    check_no_erosion(conn, f"{name}_01", f"{name}_05")
    check_valid_topology(conn, f"{name}_05", gap_maximum_width=0)

    export_geometry_table(conn, f"{name}_05", dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05_tmp3"')
