"""Loads and cleans the (already-extended) child and parent/clip layers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.extend import _01_inputs as extend_inputs


def main(
    conn: DuckDBPyConnection, name: str, input_paths: list[Path], clip_path: Path
) -> None:
    """Load, clean, and combine the (possibly multi-file) child and parent/clip layers.

    Each part is tagged with its own full path as `source_file`, since basename
    alone can't distinguish same-named files across directories.
    """
    for i, path in enumerate(input_paths):
        extend_inputs.main(conn, f"{name}_childpart{i}", path)

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

    extend_inputs.main(conn, f"{name}_parent", clip_path)
