"""Applies `{name}_02`'s freshly-mapped crosswalk via core.refactor's rename stage."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.schema_refactor._01_inputs import (
    validate_and_materialize_crosswalk,
)
from topo_tools.core.schema_refactor._02_rename import main as rename_main


def main(conn: DuckDBPyConnection, name: str, path: Path | str) -> None:
    """Rename/drop `{name}_01`'s columns per `{name}_02`, writing `{name}_apply_02`."""
    apply_name = f"{name}_apply"
    conn.execute(f"""--sql
        CREATE OR REPLACE VIEW "{apply_name}_01" AS SELECT * FROM "{name}_01"
    """)

    rows = conn.execute(f"""--sql
        SELECT source_column, target_column FROM "{name}_02"
        WHERE source_column IS NOT NULL
    """).fetchall()
    crosswalk = [{"source_column": r[0], "target_column": r[1]} for r in rows]

    validate_and_materialize_crosswalk(
        conn, apply_name, f"{apply_name}_01", crosswalk, path
    )
    rename_main(conn, apply_name)
    # Drop now, right after use: a later DROP TABLE IF EXISTS on this name
    # (core.refactor._03_outputs's own cleanup) errors on a view, not a table.
    conn.execute(f'DROP VIEW IF EXISTS "{apply_name}_01"')
