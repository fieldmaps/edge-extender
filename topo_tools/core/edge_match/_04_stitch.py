"""Single whole-table coverage-clean of the clipped, reassembled output."""

from duckdb import DuckDBPyConnection

from topo_tools.core.edge_stitch import _02_clean as clean


def main(conn: DuckDBPyConnection, name: str, *, debug: bool = False) -> None:
    """Coverage-clean the clipped output to fix cross-group seams."""
    clean.main(conn, f"{name}_04", f"{name}_05")
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
