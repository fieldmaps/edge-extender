"""Imports geodata and reprojects to EPSG:4326, validating requested columns exist."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def main(
    conn: DuckDBPyConnection,
    name: str,
    path: Path | str,
    *,
    group_by: list[str],
) -> None:
    """Import geodata; raise ValueError listing any requested column not present."""
    read_and_reproject(conn, name, path)

    table = f"{name}_01"
    columns = {row[0] for row in conn.execute(f'DESCRIBE "{table}"').fetchall()}
    missing = [c for c in group_by if c not in columns]
    if missing:
        msg = f"column(s) not found in {path}: {missing}"
        raise ValueError(msg)
