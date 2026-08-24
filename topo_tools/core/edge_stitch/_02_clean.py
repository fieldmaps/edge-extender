"""Whole-table ST_CoverageClean pass, closing seams between independent tiles."""

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import coverage_clean


def main(conn: DuckDBPyConnection, table_in: str, table_out: str) -> None:
    """Coverage-clean table_in into table_out, fixing cross-tile seams."""
    coverage_clean(conn, table_in, table_out, fids=None)
