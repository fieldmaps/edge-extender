"""Imports geodata and reprojects to EPSG:4326, without coverage-cleaning."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def main(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Import geodata into DuckDB; cleanliness is the stitch stage's own job."""
    read_and_reproject(conn, name, path)
