"""Exports each children file's own clipped subset, no coverage hard gate."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import export_geometry_table


def main(
    conn: DuckDBPyConnection,
    name: str,
    dest_by_source: dict[str, Path],
    *,
    debug: bool = False,
) -> None:
    """Export each children file's own clipped rows to its paired destination.

    Validates every children file has surviving rows before writing any
    output, so a multi-file call either fully succeeds or writes nothing.
    """
    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"clip: no child survived clipping for {name}"
        raise RuntimeError(msg)

    present = {
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT source_file FROM "{name}_03"'
        ).fetchall()
    }
    missing = [src for src in dest_by_source if src not in present]
    if missing:
        msg = f"clip: no child survived clipping for: {missing}"
        raise RuntimeError(msg)

    for source_file, dest in dest_by_source.items():
        conn.execute(f"""--sql
            CREATE OR REPLACE TEMP VIEW "{name}_03_one" AS
            SELECT * EXCLUDE (source_file) FROM "{name}_03"
            WHERE source_file = '{source_file}'
        """)
        export_geometry_table(conn, f"{name}_03_one", dest)

    if not debug:
        conn.execute(f'DROP VIEW IF EXISTS "{name}_03_one"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
