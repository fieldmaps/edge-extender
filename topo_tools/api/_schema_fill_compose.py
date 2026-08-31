"""Opt-in schema-fill composition for edge-stitch/edge-match/edge-mosaic."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.schema_fill import _02_fill as fill_stage
from topo_tools.core.schema_map._levels import detect_levels
from topo_tools.core.schema_map._target_schema import (
    DEFAULT_TARGET_SCHEMA_PATH,
    load_target_schema,
)


def validate_fill_flags(
    *, fill_schema: bool, target_schema_path: str | Path | None
) -> None:
    """Raise if target_schema_path is given without fill_schema."""
    if target_schema_path is not None and not fill_schema:
        msg = "target_schema_path requires fill_schema=True"
        raise ValueError(msg)


def apply_optional_fill(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    table: str,
    *,
    requested: bool,
    target_schema_path: str | Path | None,
    depth_column: str,
    debug: bool,
) -> None:
    """Fill table in place via schema-fill's own stage, right before export."""
    if not requested:
        return

    columns = [row[0] for row in conn.execute(f'DESCRIBE "{table}"').fetchall()]
    if depth_column in columns:
        msg = f"depth_column {depth_column!r} already exists on {table!r}"
        raise ValueError(msg)

    schema = load_target_schema(target_schema_path or DEFAULT_TARGET_SCHEMA_PATH)
    levels = detect_levels(conn, table, schema)

    pre_table = f"{name}_fill_01"
    post_table = f"{name}_fill_02"
    conn.execute(f'ALTER TABLE "{table}" RENAME TO "{pre_table}"')
    fill_stage.main(
        conn,
        pre_table,
        post_table,
        levels=levels,
        schema=schema,
        depth_column=depth_column,
    )
    conn.execute(f'ALTER TABLE "{post_table}" RENAME TO "{table}"')
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{pre_table}"')
