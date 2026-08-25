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
    result_table: str | None = None,
    raise_if_empty: bool = True,
) -> None:
    """Clip every assigned child to its parent's geometry, isolated per parent fid."""
    result_table = result_table or f"{name}_03"
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
        result_table,
        tmp_dir,
        threads=threads,
        debug=debug,
    )
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_clip_in"')

    if raise_if_empty:
        count = conn.execute(f'SELECT COUNT(*) FROM "{result_table}"').fetchone()[0]
        if count == 0:
            msg = f"mosaic: no child was assigned to any parent for {name}"
            raise RuntimeError(msg)


def fill_gaps(
    conn: DuckDBPyConnection,
    name: str,
    *,
    carry_columns: list[str] | None = None,
    result_table: str,
    parent_snapshot_table: str,
) -> None:
    """Union in the parent's own geometry for any parent matched by zero children."""
    carry_sql = "".join(f', "{c}"' for c in (carry_columns or []))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_gap_fill" AS
        SELECT fid AS parent_fid, geom{carry_sql}
        FROM "{parent_snapshot_table}"
        WHERE fid NOT IN (SELECT DISTINCT parent_fid FROM "{name}_02_assign")
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{result_table}" AS
        SELECT * FROM "{result_table}"
        UNION ALL BY NAME
        SELECT * FROM "{name}_02_gap_fill"
    """)
