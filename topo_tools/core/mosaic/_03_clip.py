"""Clips each assigned child to its own parent, one subprocess per parent fid."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.clip import clip_to_parent


def main(
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
) -> None:
    """Clip every assigned child to its parent's geometry, isolated per parent fid."""
    clip_to_parent(
        conn,
        f"{name}_child_01",
        f'"{name}_parent_01"',
        f"{name}_03",
        assign_table=f"{name}_02_assign",
        tmp_dir=tmp_dir,
        threads=threads,
        debug=debug,
    )
    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"mosaic: no child was assigned to any parent for {name}"
        raise RuntimeError(msg)
