"""Loads the children and the parent/clip layer, both raw."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def main(
    conn: DuckDBPyConnection, name: str, children_path: Path, parent_path: Path
) -> None:
    """Load both layers uncleaned; parent_fid is assigned internally downstream."""
    read_and_reproject(conn, f"{name}_child", children_path)
    read_and_reproject(conn, f"{name}_parent", parent_path)
