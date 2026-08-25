"""Loads and cleans the child and parent/clip layers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_reproject_and_clean


def load_and_clean_child(
    conn: DuckDBPyConnection, name: str, input_path: Path | str
) -> None:
    """Load and coverage-clean one child file, tagged with its own source_file."""
    read_reproject_and_clean(conn, f"{name}_child", input_path)
    # assign_one groups children by source_file (each input file is one group).
    conn.execute(f"""--sql
        ALTER TABLE "{name}_child_01"
        ADD COLUMN source_file VARCHAR DEFAULT '{input_path}'
    """)


def load_and_clean_parent(
    conn: DuckDBPyConnection, name: str, clip_path: Path | str
) -> None:
    """Load and coverage-clean the parent/clip layer."""
    read_reproject_and_clean(conn, f"{name}_parent", clip_path)


def main(
    conn: DuckDBPyConnection, name: str, input_path: Path | str, clip_path: Path | str
) -> None:
    """Load and coverage-clean both the child and parent/clip layers."""
    load_and_clean_child(conn, name, input_path)
    load_and_clean_parent(conn, name, clip_path)
