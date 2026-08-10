"""Imports geodata, reprojects to EPSG:4326, and cleans coverage violations."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import coverage_clean, has_valid_topology
from topo_tools.core.io import read_and_reproject

logger = getLogger(__name__)


def main(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Import geodata into DuckDB tables, then clean coverage topology violations."""
    read_and_reproject(conn, name, path)

    table = f"{name}_01"
    if not has_valid_topology(conn, table):
        logger.info("cleaning coverage: invalid edges or gaps detected")
        coverage_clean(
            conn,
            table,
            table,
            fids=None,
            gap_maximum_width=SNAP_TOLERANCE,
            snapping_distance=SNAP_TOLERANCE,
        )
