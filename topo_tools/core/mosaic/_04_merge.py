"""Single whole-table coverage-clean of the clipped mosaic output."""

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import coverage_clean


def main(conn: DuckDBPyConnection, name: str, *, debug: bool = False) -> None:
    """Coverage-clean the clipped output to fix cross-parent seams."""
    coverage_clean(
        conn, f"{name}_03", f"{name}_04", fids=None, gap_maximum_width=SNAP_TOLERANCE
    )
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
