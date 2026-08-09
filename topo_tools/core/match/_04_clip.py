"""Clips the whole reassembled table, one subprocess per distinct parent fid."""

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
    """Clip every group's rows to its own parent_fid's geometry."""
    clip_main(
        conn,
        f"{name}_03a",
        f'"{name}_parent_01"',
        f"{name}_04",
        tmp_dir,
        threads=threads,
        debug=debug,
    )
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03a"')
