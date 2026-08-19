"""Groups rows by attribute columns and unions their geometry per group."""

from logging import getLogger

from duckdb import DuckDBPyConnection

logger = getLogger(__name__)


def _distinct_counts(
    conn: DuckDBPyConnection,
    table: str,
    group_by: list[str],
    columns: list[str],
) -> dict[str, int]:
    """Return {column: max distinct count in any group}.

    Collapses the per-group counts to one summary row in SQL, so the result
    size is proportional to the number of `columns`, never to the number of
    groups (a global admin4 dissolve can have hundreds of thousands of
    groups).
    """
    if not columns:
        return {}
    group_by_sql = ", ".join(f'"{c}"' for c in group_by)
    counts_sql = ", ".join(
        f'COUNT(DISTINCT "{c}") AS "__auto_{i}"' for i, c in enumerate(columns)
    )
    summary_sql = ", ".join(f'MAX("__auto_{i}")' for i in range(len(columns)))
    row = conn.execute(f"""--sql
        WITH counts AS (
            SELECT {group_by_sql}, {counts_sql}
            FROM "{table}"
            GROUP BY {group_by_sql}
        )
        SELECT {summary_sql} FROM counts
    """).fetchall()[0]
    return dict(zip(columns, row, strict=True))


def main(
    conn: DuckDBPyConnection,
    table_in: str,
    table_out: str,
    *,
    group_by: list[str],
) -> None:
    """Dissolve table_in into table_out, grouping by `group_by`, unioning geometry.

    A NULL value in a `group_by` column forms its own group like any other
    value (DuckDB's native GROUP BY semantics, matching GDAL's `combine
    --group-by`). Every non-`group_by` column is kept (any_value) if it's
    constant within every group, dropped (with a warning naming every
    dropped column) if not.
    """
    always_excluded = {*group_by, "fid", "geom"}
    all_cols = {row[0] for row in conn.execute(f'DESCRIBE "{table_in}"').fetchall()}
    candidate_cols = sorted(all_cols - always_excluded)

    stats = _distinct_counts(conn, table_in, group_by, candidate_cols)
    kept_cols = [c for c in candidate_cols if stats[c] <= 1]
    dropped_cols = [c for c in candidate_cols if stats[c] > 1]
    if dropped_cols:
        logger.warning(
            "dissolve: dropping %d column(s) not constant within every group: %s",
            len(dropped_cols),
            dropped_cols,
        )

    group_by_sql = ", ".join(f'"{c}"' for c in group_by)
    kept_sql = "".join(f', any_value("{c}") AS "{c}"' for c in kept_cols)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{table_out}" AS
        SELECT row_number() OVER () AS fid, {group_by_sql}{kept_sql},
               ST_MakeValid(ST_Union_Agg(geom)) AS geom
        FROM "{table_in}"
        GROUP BY {group_by_sql}
    """)
