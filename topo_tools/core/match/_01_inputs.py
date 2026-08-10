"""Loads and cleans the child and parent/clip layers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_reproject_and_clean


def main(
    conn: DuckDBPyConnection, name: str, input_path: Path, clip_path: Path
) -> None:
    """Load and coverage-clean both the child and parent/clip layers."""
    read_reproject_and_clean(conn, f"{name}_child", input_path)
    read_reproject_and_clean(conn, f"{name}_parent", clip_path)
