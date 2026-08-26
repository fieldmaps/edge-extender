"""Validates topology and exports output files from the final merged geometry table."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import check_valid_topology
from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Output results to dest."""
    # SNAP_TOLERANCE-buffered, not exact ST_Covers: GEOS leaves float noise
    # far below this scale on every polygon it touches, real erosion doesn't.
    eroded = conn.execute(f"""--sql
        SELECT count(*) FROM "{name}_01" o
        JOIN "{name}_05" e USING (fid)
        WHERE NOT ST_Covers(ST_Buffer(e.geom, {SNAP_TOLERANCE}), o.geom)
    """).fetchall()[0][0]
    if eroded > 0:
        msg = f"extension eroded the original footprint of {eroded} fid(s)"
        raise RuntimeError(msg)

    check_valid_topology(conn, f"{name}_05", gap_maximum_width=0)

    export_geometry_table(conn, f"{name}_05", dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_05_tmp3"')
