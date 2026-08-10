"""Loads the (possibly multi-file) child layer and the parent/clip layer, both raw."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def load_children(conn: DuckDBPyConnection, name: str, input_paths: list[Path]) -> None:
    """Load/combine the (possibly multi-file) children, uncleaned.

    Each child part is tagged with its own full path as `source_file`, since
    basename alone can't distinguish same-named files across directories.
    """
    for i, path in enumerate(input_paths):
        read_and_reproject(conn, f"{name}_childpart{i}", path)

    union_sql = " UNION ALL BY NAME ".join(
        f"SELECT *, '{path}' AS source_file FROM \"{name}_childpart{i}_01\""
        for i, path in enumerate(input_paths)
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_child_01" AS
        SELECT * EXCLUDE (fid), row_number() OVER () AS fid
        FROM ({union_sql})
    """)
    for i in range(len(input_paths)):
        conn.execute(f'DROP TABLE IF EXISTS "{name}_childpart{i}_01"')


def load_parent(conn: DuckDBPyConnection, name: str, clip_path: Path) -> None:
    """Load the parent/clip layer, uncleaned."""
    read_and_reproject(conn, f"{name}_parent", clip_path)


def main(
    conn: DuckDBPyConnection, name: str, input_paths: list[Path], clip_path: Path
) -> None:
    """Load/combine the (possibly multi-file) children; load the parent.

    Both loaded uncleaned.
    """
    load_children(conn, name, input_paths)
    load_parent(conn, name, clip_path)
