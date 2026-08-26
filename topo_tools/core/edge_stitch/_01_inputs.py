"""Imports geodata and reprojects to EPSG:4326, without coverage-cleaning."""

from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.io import read_and_reproject, reproject_select_sql


def main(
    conn: DuckDBPyConnection, name: str, path: Path | str | list[Path | str]
) -> None:
    """Import geodata into DuckDB; cleanliness is the stitch stage's own job.

    A list of paths is combined into one table before returning, since the
    whole-table coverage-clean pass downstream needs a single tiled layer.
    """
    if isinstance(path, (str, Path)):
        read_and_reproject(conn, name, path)
        return

    union_sql = " UNION ALL BY NAME ".join(
        f"({reproject_select_sql(conn, p)})" for p in path
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_01" AS
        SELECT * EXCLUDE (fid), row_number() OVER () AS fid
        FROM ({union_sql})
    """)
