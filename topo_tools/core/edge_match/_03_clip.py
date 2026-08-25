"""Clips the whole reassembled table, one subprocess per distinct parent fid."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.edge_clip import main as clip_main
from topo_tools.core.edge_match._constants import PASSTHROUGH_PARENT_FID


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
    passthrough: bool = False,
) -> None:
    """Clip every real group's rows to its own parent_fid's geometry.

    With passthrough=True, the orphan group's rows (PASSTHROUGH_PARENT_FID)
    are split out first and unioned back in afterward, unclipped.
    """
    clip_in = f"{name}_03a"
    if passthrough:
        clip_in = f"{name}_03a_real"
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{clip_in}" AS
            SELECT * FROM "{name}_03a" WHERE parent_fid != {PASSTHROUGH_PARENT_FID}
        """)

    clip_main(
        conn,
        clip_in,
        f'"{name}_parent_01"',
        f"{name}_04",
        tmp_dir,
        threads=threads,
        debug=debug,
    )

    if passthrough:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_04" AS
            SELECT * FROM "{name}_04"
            UNION ALL BY NAME
            SELECT * EXCLUDE (parent_fid) FROM "{name}_03a"
            WHERE parent_fid = {PASSTHROUGH_PARENT_FID}
        """)
        if not debug:
            conn.execute(f'DROP TABLE IF EXISTS "{clip_in}"')

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03a"')
