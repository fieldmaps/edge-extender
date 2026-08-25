"""Coverage-cleans the child layer; loads the parent/clip layer raw."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import load_parent
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


def main(
    conn: DuckDBPyConnection, name: str, input_path: Path | str, clip_path: Path | str
) -> None:
    """Coverage-clean the child layer; load the parent/clip layer raw."""
    load_and_clean_child(conn, name, input_path)
    load_parent(conn, name, clip_path)
