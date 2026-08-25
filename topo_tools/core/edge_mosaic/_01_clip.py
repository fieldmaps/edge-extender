"""Clips each assigned child to its own parent, one subprocess per parent fid."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.edge_clip import main as clip_main


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    tmp_dir: Path,
    *,
    threads: int | None = None,
    debug: bool = False,
    carry_columns: list[str] | None = None,
    passthrough: bool = False,
) -> None:
    """Clip every assigned child to its parent's geometry, isolated per parent fid."""
    carry_sql = "".join(f', a."{c}" AS "{c}"' for c in (carry_columns or []))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_clip_in" AS
        SELECT c.*, a.parent_fid{carry_sql}
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

    if passthrough:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_passthrough" AS
            SELECT * FROM "{name}_child_01"
            WHERE source_file IN (
                SELECT DISTINCT source_file FROM "{name}_child_01"
                EXCEPT
                SELECT DISTINCT c.source_file
                FROM "{name}_child_01" c
                JOIN "{name}_02_assign" a ON a.child_fid = c.fid
            )
        """)
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_03" AS
            SELECT * FROM "{name}_03"
            UNION ALL BY NAME
            SELECT * FROM "{name}_02_passthrough"
        """)

    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"mosaic: no child was assigned to any parent for {name}"
        raise RuntimeError(msg)
