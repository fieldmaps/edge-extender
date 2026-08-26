"""Loads the (possibly multi-file) child layer and the parent/clip layer, both raw."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject, reproject_select_sql


def load_children(
    conn: DuckDBPyConnection, name: str, input_paths: list[Path | str]
) -> None:
    """Load/combine the (possibly multi-file) children, uncleaned.

    Each part is tagged with its own full path as `source_file` (basename
    alone can't distinguish same-named files across directories).
    """
    union_sql = " UNION ALL BY NAME ".join(
        f"(SELECT *, '{path}' AS source_file FROM ({reproject_select_sql(conn, path)}))"
        for path in input_paths
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_child_01" AS
        SELECT * EXCLUDE (fid), row_number() OVER () AS fid
        FROM ({union_sql})
    """)


def load_parent(conn: DuckDBPyConnection, name: str, clip_path: Path | str) -> None:
    """Load the parent/clip layer, uncleaned."""
    read_and_reproject(conn, f"{name}_parent", clip_path)
