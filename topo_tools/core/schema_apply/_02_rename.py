"""Renames/drops columns per the validated crosswalk."""

from duckdb import DuckDBPyConnection

from topo_tools.core.duckdb_utils import quote_identifier


def main(conn: DuckDBPyConnection, name: str) -> None:
    """Apply `{name}_crosswalk` to `{name}_01`, writing `{name}_02`.

    A source column whose target_column is null/empty is dropped; every
    other source column is renamed to its target_column.
    """
    rows = conn.execute(
        f'SELECT source_column, target_column FROM "{name}_crosswalk"'
    ).fetchall()
    select_cols = [
        f"{quote_identifier(source)} AS {quote_identifier(target)}"
        for source, target in rows
        if target
    ]
    extra = f", {', '.join(select_cols)}" if select_cols else ""

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" AS
        SELECT fid, geom{extra} FROM "{name}_01"
    """)
