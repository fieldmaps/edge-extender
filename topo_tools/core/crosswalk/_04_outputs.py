"""Exports the crosswalk CSV and mapped output, reusing map's/refactor's writers."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.map import _03_outputs as map_outputs
from topo_tools.core.refactor import _03_outputs as refactor_outputs


def main(
    conn: DuckDBPyConnection,
    name: str,
    crosswalk_path: Path,
    output_path: Path,
    *,
    debug: bool = False,
) -> None:
    """Export `{name}_02` to crosswalk_path and `{name}_apply_02` to output_path."""
    map_outputs.main(conn, name, crosswalk_path, debug=debug)
    refactor_outputs.main(conn, f"{name}_apply", output_path, debug=debug)
