"""Joins parent_fid onto the combined children table, then clips per parent fid."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from ._engine import main as clip_engine


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
    carry_columns: list[str] | None = None,
) -> None:
    """Clip every assigned child to its parent's geometry, isolated per parent fid."""
    carry_sql = "".join(f', a."{c}" AS "{c}"' for c in (carry_columns or []))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_clip_in" AS
        SELECT c.*, a.parent_fid{carry_sql}
        FROM "{name}_child_01" c
        JOIN "{name}_02_assign" a ON a.child_fid = c.fid
    """)
    clip_engine(
        conn,
        f"{name}_02_clip_in",
        f'"{name}_parent_01"',
        f"{name}_03",
        tmp_dir,
        threads=threads,
        debug=debug,
    )
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_clip_in"')
