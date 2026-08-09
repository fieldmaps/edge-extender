"""Loads and cleans the child and parent/clip layers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.extend import _01_inputs as extend_inputs


def main(
    conn: DuckDBPyConnection, name: str, input_path: Path, clip_path: Path
) -> None:
    """Load and coverage-clean both the child and parent/clip layers."""
    extend_inputs.main(conn, f"{name}_child", input_path)
    extend_inputs.main(conn, f"{name}_parent", clip_path)
