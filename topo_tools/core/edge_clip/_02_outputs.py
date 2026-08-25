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
    """Export each children file's own clipped rows and per-file issues report.

    clip-empty rows always included; code-mismatch/code-fallback when code_join.
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

    issue_parts = [
        f"""
        SELECT 'clip-empty-' || fid AS key, 'clip-empty' AS kind,
               fid AS unit_a, NULL::BIGINT AS unit_b, parent_fid,
               'clip intersection with its assigned parent was empty' AS reason,
               NULL::DOUBLE AS area_m2, NULL::DOUBLE AS max_width_m,
               NULL::DOUBLE AS thinness_ratio,
               NULL::DOUBLE AS unit_a_area_change_m2,
               NULL::DOUBLE AS unit_b_area_change_m2,
               NULL::DOUBLE AS filled_area_m2, FALSE AS fixed, source_file, geom
        FROM "{name}_03_dropped"
    """
    ]
    if code_join:
        issue_parts.append(
            assign_issue_rows_sql(name, source_file_expr="c.source_file")
        )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_issues" AS
        {" UNION ALL BY NAME ".join(issue_parts)}
    """)

    for source_file, dest in dest_by_source.items():
        conn.execute(f"""--sql
            CREATE OR REPLACE TEMP VIEW "{name}_03_one" AS
            SELECT * EXCLUDE (source_file) FROM "{name}_03"
            WHERE source_file = '{source_file}'
        """)
        export_geometry_table(conn, f"{name}_03_one", dest)

        if issues_dest_by_source and source_file in issues_dest_by_source:
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
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03_dropped"')
