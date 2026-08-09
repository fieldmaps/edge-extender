"""Loads the children (already carrying parent_fid) and the parent/clip layer, raw."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def main(
    conn: DuckDBPyConnection, name: str, children_path: Path, parent_path: Path
) -> None:
    """Load both layers uncleaned; raise if the children lack a parent_fid column."""
    read_and_reproject(conn, f"{name}_child", children_path)
    columns = [row[0] for row in conn.execute(f'DESCRIBE "{name}_child_01"').fetchall()]
    if "parent_fid" not in columns:
        msg = (
            f"clip: {children_path} has no parent_fid column -- run assign-many "
            "or assign-one first"
        )
        raise ValueError(msg)

    read_and_reproject(conn, f"{name}_parent", parent_path)
