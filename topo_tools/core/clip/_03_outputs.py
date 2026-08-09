"""Exports the clipped output -- no coverage hard gate, that's stitch's job."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Export the clipped layer to dest."""
    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_02"').fetchone()[0]
    if count == 0:
        msg = f"clip: no child survived clipping for {name}"
        raise RuntimeError(msg)

    export_geometry_table(conn, f"{name}_02", dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
