"""Exports the filled-down output."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Export `{name}_02` to dest.

    No topology hard-gate here: fill only fills attribute columns and
    stamps a depth column, it never touches geometry.
    """
    export_geometry_table(conn, f"{name}_02", dest)

    if not debug:
        for t in (f"{name}_01", f"{name}_02"):
            conn.execute(f'DROP TABLE IF EXISTS "{t}"')
