"""Imports leaf-level geodata, validating every hierarchy level has a code column."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject
from topo_tools.core.schema_map._target_schema import TargetSchema

from ._levels import detect_levels


def main(
    conn: DuckDBPyConnection, name: str, path: Path | str, schema: TargetSchema
) -> None:
    """Import geodata; raise ValueError early if a level lacks a code column."""
    read_and_reproject(conn, name, path)
    detect_levels(conn, f"{name}_01", schema)
