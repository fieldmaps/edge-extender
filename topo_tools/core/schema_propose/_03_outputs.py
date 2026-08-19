"""Exports the proposed source-to-target crosswalk as JSON."""

import json
from pathlib import Path

from duckdb import DuckDBPyConnection


def main(
    conn: DuckDBPyConnection, name: str, dest: Path, *, debug: bool = False
) -> None:
    """Export `{name}_02` (the proposed crosswalk) to dest as JSON."""
    rows = conn.execute(f"""--sql
        SELECT source_column, target_column, confidence, note
        FROM "{name}_02"
        ORDER BY column_order
    """).fetchall()

    dest.parent.mkdir(exist_ok=True, parents=True)
    crosswalk = [
        {"source_column": r[0], "target_column": r[1], "confidence": r[2], "note": r[3]}
        for r in rows
    ]
    dest.write_text(json.dumps(crosswalk, indent=2) + "\n")

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
