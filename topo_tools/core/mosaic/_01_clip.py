"""Clips each assigned child to its own parent, one subprocess per parent fid."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.clip import main as clip_main


def main(
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
) -> None:
    """Clip every assigned child to its parent's geometry, isolated per parent fid."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_clip_in" AS
        SELECT c.*, a.parent_fid
        FROM "{name}_child_01" c
        JOIN "{name}_02_assign" a ON a.child_fid = c.fid
    """)
    clip_main(
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

    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"mosaic: no child was assigned to any parent for {name}"
        raise RuntimeError(msg)
