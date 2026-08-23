"""Exports the proposed source-to-target crosswalk as CSV."""

import csv
from pathlib import Path

from duckdb import DuckDBPyConnection

_FIELDNAMES = ["source_column", "target_column", "unique_count", "note"]


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Export `{name}_02` (the proposed crosswalk) to dest as CSV."""
    rows = conn.execute(f"""--sql
        SELECT source_column, target_column, unique_count, note
        FROM "{name}_02"
        ORDER BY column_order
    """).fetchall()

    dest.parent.mkdir(exist_ok=True, parents=True)
    with dest.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDNAMES)
        writer.writerows(rows)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
