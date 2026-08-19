"""Reads the input file and crosswalk, validating the crosswalk against it."""

import json
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject


def _parse_crosswalk(crosswalk_path: Path) -> list[dict]:
    """Load the crosswalk JSON, raising ValueError on any shape violation."""
    crosswalk = json.loads(crosswalk_path.read_text())
    if not isinstance(crosswalk, list):
        msg = (
            f"crosswalk must be a JSON list of "
            f"{{source_column, target_column}} objects: {crosswalk_path}"
        )
        raise ValueError(msg)  # noqa: TRY004 -- ValueError, not TypeError, is caught by the CLI
    try:
        source_columns = [row["source_column"] for row in crosswalk]
    except (KeyError, TypeError) as e:
        msg = (
            f"crosswalk entries must be objects with a source_column key: "
            f"{crosswalk_path}"
        )
        raise ValueError(msg) from e

    dupes = sorted({c for c in source_columns if source_columns.count(c) > 1})
    if dupes:
        msg = f"crosswalk lists the same source_column more than once: {dupes}"
        raise ValueError(msg)
    return crosswalk


def _validate_columns_match(
    crosswalk_columns: set[str], actual_columns: set[str], path: Path | str
) -> None:
    """Raise ValueError unless crosswalk_columns exactly equals actual_columns."""
    missing = crosswalk_columns - actual_columns
    extra = actual_columns - crosswalk_columns
    if missing or extra:
        details = []
        if missing:
            details.append(
                f"crosswalk references column(s) not in the file: {sorted(missing)}"
            )
        if extra:
            details.append(
                f"file has column(s) not decided in the crosswalk: {sorted(extra)}"
            )
        msg = (
            f"crosswalk does not match the columns in {path} "
            f"({'; '.join(details)}; stale crosswalk, or wrong input file?)"
        )
        raise ValueError(msg)


def _validate_targets(crosswalk: list[dict]) -> None:
    """Raise ValueError on a duplicate or reserved-name target_column."""
    targets = [row["target_column"] for row in crosswalk if row.get("target_column")]
    duplicates = sorted({t for t in targets if targets.count(t) > 1})
    reserved_hits = sorted(set(targets) & {"fid", "geom", "geometry"})
    if duplicates or reserved_hits:
        details = []
        if duplicates:
            details.append(f"target_column value(s) used more than once: {duplicates}")
        if reserved_hits:
            details.append(
                f"target_column value(s) collide with reserved names: {reserved_hits}"
            )
        msg = f"crosswalk has invalid target_column value(s) ({'; '.join(details)})"
        raise ValueError(msg)


def main(
    conn: DuckDBPyConnection, name: str, path: Path | str, crosswalk_path: Path
) -> None:
    """Read geodata into `{name}_01`; validate the crosswalk exactly covers it."""
    read_and_reproject(conn, name, path)

    crosswalk = _parse_crosswalk(crosswalk_path)
    table = f"{name}_01"
    actual_columns = {
        r[0]
        for r in conn.execute(f'DESCRIBE "{table}"').fetchall()
        if r[0] not in {"fid", "geom"}
    }
    crosswalk_columns = {row["source_column"] for row in crosswalk}
    _validate_columns_match(crosswalk_columns, actual_columns, path)
    _validate_targets(crosswalk)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_crosswalk" (
            source_column VARCHAR, target_column VARCHAR
        )
    """)
    for row in crosswalk:
        conn.execute(
            f'INSERT INTO "{name}_crosswalk" VALUES (?, ?)',
            [row["source_column"], row.get("target_column") or None],
        )
