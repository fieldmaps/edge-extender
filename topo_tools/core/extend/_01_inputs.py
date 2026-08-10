"""Imports geodata, reprojects to EPSG:4326, and cleans coverage violations."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_reproject_and_clean


def main(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Import geodata into DuckDB tables, then clean coverage topology violations."""
    read_reproject_and_clean(conn, name, path)
