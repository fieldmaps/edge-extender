"""Loads and cleans the old (Version A) and new (Version B) layers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.extend import _01_inputs as extend_inputs


def main(conn: DuckDBPyConnection, name: str, old_path: Path, new_path: Path) -> None:
    """Load and coverage-clean both comparison layers."""
    extend_inputs.main(conn, f"{name}_a", old_path)
    extend_inputs.main(conn, f"{name}_b", new_path)
