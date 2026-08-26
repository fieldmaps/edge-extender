"""Unions in a parent's own geometry for any parent matched by zero children."""

from duckdb import DuckDBPyConnection


def fill_unmatched_parents(
    conn: DuckDBPyConnection,
    name: str,
    *,
    carry_columns: list[str] | None = None,
    result_table: str,
    parent_snapshot_table: str,
) -> None:
    """Append each zero-children parent's own row (unclipped) onto result_table."""
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
