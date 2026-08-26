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
    """Append each zero-children parent's own row (unclipped) onto result_table.

    One INSERT per fid, not one bulk copy: a true global parent can leave
    most of its rows unmatched, so this avoids materializing them all at once.
    """
    carry_sql = "".join(f', "{c}"' for c in (carry_columns or []))
    # result_table's clip output may lack parent_fid/a carry column entirely;
    # add every column BY NAME below relies on, even with zero unmatched fids.
    column_types = {
        row[0]: row[1]
        for row in conn.execute(f'DESCRIBE "{parent_snapshot_table}"').fetchall()
    }
    for column, column_type in [("parent_fid", column_types["fid"])] + [
        (c, column_types[c]) for c in (carry_columns or [])
    ]:
        conn.execute(f"""--sql
            ALTER TABLE "{result_table}"
            ADD COLUMN IF NOT EXISTS "{column}" {column_type}
        """)
    fids = conn.execute(f"""--sql
        SELECT fid FROM "{parent_snapshot_table}"
        WHERE fid NOT IN (SELECT DISTINCT parent_fid FROM "{name}_02_assign")
    """).fetchall()
    for (fid,) in fids:
        conn.execute(f"""--sql
            INSERT INTO "{result_table}" BY NAME
            SELECT fid AS parent_fid, geom{carry_sql}
            FROM "{parent_snapshot_table}"
            WHERE fid = {fid}
        """)
