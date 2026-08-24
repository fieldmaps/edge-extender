"""Exports each children file's own clipped subset, no coverage hard gate."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import assign_issue_rows_sql
from topo_tools.core.io import export_geometry_table, export_issues_table


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    dest_by_source: dict[str, Path],
    issues_dest_by_source: dict[str, Path] | None = None,
    *,
    code_join: bool = False,
    debug: bool = False,
) -> None:
    """Export each children file's own clipped rows to its paired destination.

    Validates every children file has surviving rows before writing any
    output, so a multi-file call either fully succeeds or writes nothing.

    When code_join is set, also exports a per-file issues report of
    code-mismatch/code-fallback rows (clip has no topology hard gate of its
    own, so this is the only issue kind it can report); issues_dest_by_source
    is otherwise unused.
    """
    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"clip: no child survived clipping for {name}"
        raise RuntimeError(msg)

    present = {
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT source_file FROM "{name}_03"'
        ).fetchall()
    }
    missing = [src for src in dest_by_source if src not in present]
    if missing:
        msg = f"clip: no child survived clipping for: {missing}"
        raise RuntimeError(msg)

    if code_join:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_issues" AS
            {assign_issue_rows_sql(name, source_file_expr="c.source_file")}
        """)

    for source_file, dest in dest_by_source.items():
        conn.execute(f"""--sql
            CREATE OR REPLACE TEMP VIEW "{name}_03_one" AS
            SELECT * EXCLUDE (source_file) FROM "{name}_03"
            WHERE source_file = '{source_file}'
        """)
        export_geometry_table(conn, f"{name}_03_one", dest)

        if code_join and issues_dest_by_source and source_file in issues_dest_by_source:
            conn.execute(f"""--sql
                CREATE OR REPLACE TEMP VIEW "{name}_02_issues_one" AS
                SELECT * EXCLUDE (source_file) FROM "{name}_02_issues"
                WHERE source_file = '{source_file}'
            """)
            export_issues_table(
                conn, f"{name}_02_issues_one", issues_dest_by_source[source_file]
            )

    if not debug:
        conn.execute(f'DROP VIEW IF EXISTS "{name}_03_one"')
        conn.execute(f'DROP VIEW IF EXISTS "{name}_02_issues_one"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_issues"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_pairs"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
