"""Fills NULL adm{n}<suffix> columns down and stamps each row's real depth."""

from duckdb import DuckDBPyConnection

from topo_tools.core.schema_map._levels import (
    column_families,
    field_prefix,
    level_prefix,
)
from topo_tools.core.schema_map._target_schema import TargetSchema


def _depth_column_sql(code_columns: dict[int, str], depth_column: str) -> str:
    """Build a CASE expression stamping the deepest level with a non-NULL code."""
    cases = "\n".join(
        f'WHEN "{code_columns[lvl]}" IS NOT NULL THEN {lvl}'
        for lvl in sorted(code_columns, reverse=True)
    )
    return f'CASE {cases} END AS "{depth_column}"'


def main(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    table_in: str,
    table_out: str,
    *,
    levels: list[int],
    schema: TargetSchema,
    depth_column: str,
) -> None:
    """Build table_out: fill each name/code column family, stamp the depth column."""
    code_prefix = level_prefix(schema)
    name_prefix = field_prefix(schema.name_field)
    code_suffix = schema.code_field.split("{n}", 1)[1]

    columns = [row[0] for row in conn.execute(f'DESCRIBE "{table_in}"').fetchall()]

    filled_columns: set[str] = set()
    filled_select_parts: list[str] = []
    code_columns: dict[int, str] = {}
    for prefix in dict.fromkeys([code_prefix, name_prefix]):
        families = column_families(columns, levels, prefix)
        if prefix == code_prefix:
            code_columns = families.get(code_suffix, {})
        for per_level in families.values():
            filled_columns.update(per_level.values())
            for level in sorted(per_level):
                chain = [per_level[k] for k in sorted(per_level) if k <= level]
                if len(chain) > 1:
                    coalesce = ", ".join(f'"{c}"' for c in reversed(chain))
                    filled_select_parts.append(
                        f'COALESCE({coalesce}) AS "{per_level[level]}"'
                    )
                else:
                    filled_select_parts.append(f'"{per_level[level]}"')

    select_parts = [
        f'"{c}"' for c in columns if c not in filled_columns
    ] + filled_select_parts
    select_parts.append(_depth_column_sql(code_columns, depth_column))

    select_sql = ", ".join(select_parts)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{table_out}" AS SELECT {select_sql} FROM "{table_in}"
    """)
