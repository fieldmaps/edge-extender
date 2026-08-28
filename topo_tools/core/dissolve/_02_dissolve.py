"""Groups rows by attribute columns and unions their geometry per group."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.schema_map._levels import (
    column_families,
    detect_levels,
    level_prefix,
)
from topo_tools.core.schema_map._target_schema import TargetSchema

logger = getLogger(__name__)


def _distinct_counts(
    conn: DuckDBPyConnection,
    table: str,
    group_by: list[str],
    columns: list[str],
) -> dict[str, int]:
    """Return {column: max distinct count in any group}.

    Collapses per-group counts to one summary row in SQL, so result size
    scales with `columns`, never with group count (can be hundreds of thousands).
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


def _schema_derived_exclusions(
    conn: DuckDBPyConnection,
    table: str,
    group_by: list[str],
    schema: TargetSchema,
) -> set[str]:
    """Return every column at a level finer than group_by's own detected level."""
    columns = [row[0] for row in conn.execute(f'DESCRIBE "{table}"').fetchall()]
    levels = detect_levels(conn, table, schema)

    target_level = None
    for level in sorted(levels, reverse=True):
        if schema.code_field.format(n=level) in group_by or (
            schema.name_field.format(n=level) in group_by
        ):
            target_level = level
            break
    if target_level is None:
        msg = (
            "target_schema given but no group_by column matches any "
            f"detected level: {group_by}"
        )
        raise ValueError(msg)

    finer_levels = [level for level in levels if level > target_level]
    prefix = level_prefix(schema)
    families = column_families(columns, finer_levels, prefix)
    return {column for per_level in families.values() for column in per_level.values()}


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    table_in: str,
    table_out: str,
    *,
    group_by: list[str],
    exclude: list[str] | None = None,
    target_schema: TargetSchema | None = None,
) -> None:
    """Dissolve table_in into table_out, grouping by `group_by`, unioning geometry.

    A NULL `group_by` value forms its own group (matching GDAL's
    `combine --group-by`); other columns are kept if constant per group, else dropped.
    """
    always_excluded = {*group_by, "fid", "geom", *(exclude or [])}
    if target_schema is not None:
        always_excluded |= _schema_derived_exclusions(
            conn, table_in, group_by, target_schema
        )
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
