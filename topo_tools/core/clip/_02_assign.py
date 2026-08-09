"""Assigns each child to its one shared parent via assign-one, before clipping."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import _02_one as assign


def main(conn: DuckDBPyConnection, name: str, children_path: Path) -> None:
    """Tag children with source_file, run assign-one, then join parent_fid onto them."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_child_01" AS
        SELECT *, '{children_path}' AS source_file FROM "{name}_child_01"
    """)
    assign.main(conn, name)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_clip_in" AS
        SELECT c.*, a.parent_fid
        FROM "{name}_child_01" c
        JOIN "{name}_02_assign" a ON a.child_fid = c.fid
    """)
