"""Structurally discovers a source file's admin hierarchy and code/name roles.

See docs/explanation/map.md and docs/adr/0054 for the algorithm and why.
"""

import re
from dataclasses import dataclass

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import NOISE_COLUMNS
from topo_tools.core.duckdb_utils import quote_identifier
from topo_tools.core.map._constants import CONFIDENCE_AMBIGUOUS
from topo_tools.core.map._target_schema import TargetSchema

# fid/geom are topo-tools' own internal columns, never candidate source data.
_EXCLUDED_COLUMNS = {"fid", "geom"}

# COD-AB's own documented p-code format: letter prefix + numeric suffix
# (e.g. "MG11101001035"); a majority match is a strong code-vs-name signal.
_CODE_SHAPE_REGEX = r"^[A-Za-z]{1,4}[0-9]+$"
_CODE_SHAPE_MIN_RATE = 0.75
_NAME_SHAPE_MAX_RATE = 0.10

# COD-AB's admin0 pcode is a bare ISO2/3 country code, no digit suffix, so it
# fails _CODE_SHAPE_REGEX; a constant column matching this is code-shaped too.
_CONSTANT_CODE_REGEX = r"^[A-Z]{1,4}$"


@dataclass
class _Row:
    source_column: str | None
    target_column: str | None
    note: str
    role: str | None = None  # "code" or "name", for output ordering
    level: int | None = None
    unique_count: int | None = None


def _candidate_columns(conn: DuckDBPyConnection, table: str) -> list[str]:
    rows = conn.execute(f'DESCRIBE "{table}"').fetchall()
    return [
        r[0]
        for r in rows
        if r[0] not in _EXCLUDED_COLUMNS and r[0].lower() not in NOISE_COLUMNS
    ]


def _distinct_counts(
    conn: DuckDBPyConnection, table: str, columns: list[str]
) -> dict[str, int]:
    """One query, COUNT(DISTINCT) for every column, keyed by column name."""
    if not columns:
        return {}
    select = ", ".join(f"COUNT(DISTINCT {quote_identifier(c)})" for c in columns)
    result = conn.execute(f"SELECT {select} FROM {quote_identifier(table)}").fetchone()
    return dict(zip(columns, result, strict=True))


def _shape_classify(
    conn: DuckDBPyConnection, table: str, columns: list[str]
) -> dict[str, str]:
    """Classify each column "code"/"name"/"ambiguous" by its own values alone."""
    if not columns:
        return {}
    select = ", ".join(
        f"""--sql
        CAST(COUNT(*) FILTER (
            WHERE regexp_matches(CAST({quote_identifier(c)} AS VARCHAR),
                                  '{_CODE_SHAPE_REGEX}')
        ) AS DOUBLE) / NULLIF(COUNT({quote_identifier(c)}), 0)
        """
        for c in columns
    )
    rates = conn.execute(f"SELECT {select} FROM {quote_identifier(table)}").fetchone()
    result = {}
    for c, rate in zip(columns, rates, strict=True):
        if rate is not None and rate >= _CODE_SHAPE_MIN_RATE:
            result[c] = "code"
        elif rate is not None and rate <= _NAME_SHAPE_MAX_RATE:
            result[c] = "name"
        else:
            result[c] = "ambiguous"
    return result


def _reclassify_constant_codes(
    conn: DuckDBPyConnection,
    table: str,
    columns: list[str],
    shapes: dict[str, str],
    counts: dict[str, int],
) -> None:
    """Reclassify a constant bare-uppercase column (e.g. a country code) as code."""
    for c in columns:
        if shapes[c] == "code" or counts[c] != 1:
            continue
        value = conn.execute(
            f"SELECT MAX({quote_identifier(c)}) FROM {quote_identifier(table)}"
        ).fetchone()[0]
        if value is not None and re.match(_CONSTANT_CODE_REGEX, str(value)):
            shapes[c] = "code"


def _containment_holds(
    conn: DuckDBPyConnection, table: str, coarser: str, finer: str
) -> bool:
    """Check that every value of `finer` maps to exactly one value of `coarser`."""
    bad = conn.execute(f"""--sql
        SELECT COUNT(*) FROM (
            SELECT {quote_identifier(finer)} FROM {quote_identifier(table)}
            GROUP BY {quote_identifier(finer)}
            HAVING COUNT(DISTINCT {quote_identifier(coarser)}) > 1
        )
    """).fetchone()[0]
    return bad == 0


def _bijective(conn: DuckDBPyConnection, table: str, a: str, b: str) -> bool:
    """Check that a and b's values correspond 1:1 (same-level companions)."""
    return _containment_holds(conn, table, a, b) and _containment_holds(
        conn, table, b, a
    )


def _combined_distinct_count(
    conn: DuckDBPyConnection, table: str, parent: str, column: str
) -> int:
    """COUNT(DISTINCT (parent, column)), catching a value reused across parents."""
    return conn.execute(f"""--sql
        SELECT COUNT(*) FROM (
            SELECT DISTINCT {quote_identifier(parent)}, {quote_identifier(column)}
            FROM {quote_identifier(table)}
        )
    """).fetchone()[0]


def _build_code_groups(
    conn: DuckDBPyConnection, table: str, columns: list[str], counts: dict[str, int]
) -> list[tuple[int, list[str]]]:
    """Group code-shaped columns by distinct count, verifying same-count bijection.

    A constant (single-value) column is kept, unlike the general structural
    case: a single-country file's admin0 code is legitimately constant.
    """
    by_count: dict[int, list[str]] = {}
    for c in columns:
        by_count.setdefault(counts[c], []).append(c)

    groups: list[tuple[int, list[str]]] = []
    for count, cols in by_count.items():
        if len(cols) == 1:
            groups.append((count, cols))
            continue
        all_bijective = all(
            _bijective(conn, table, a, b)
            for i, a in enumerate(cols)
            for b in cols[i + 1 :]
        )
        if all_bijective:
            groups.append((count, cols))
        else:
            groups.extend((count, [c]) for c in cols)
    groups.sort(key=lambda g: g[0])
    return groups


def _chain_from_groups(
    conn: DuckDBPyConnection, table: str, groups: list[tuple[int, list[str]]]
) -> list[list[tuple[int, list[str]]]]:
    """Split groups into chains at any failed adjacent containment check."""
    if not groups:
        return []
    chains: list[list[tuple[int, list[str]]]] = [[groups[0]]]
    for group in groups[1:]:
        _prev_count, prev_cols = chains[-1][-1]
        _cur_count, cur_cols = group
        joins = all(
            _containment_holds(conn, table, coarser=a, finer=b)
            for a in prev_cols
            for b in cur_cols
        )
        if joins:
            chains[-1].append(group)
        else:
            chains.append([group])
    return chains


def _numbered_target(template: str, level: int, index: int) -> str:
    """Render a level's template, suffixing the 2nd+ same-level column 1, 2, ..."""
    rendered = template.format(n=level)
    return rendered if index == 0 else f"{rendered}{index}"


def _bracket_index(code_counts: list[int], count: int) -> int | None:
    """Find the sole chain index k where code_counts[k-1] < count <= code_counts[k]."""
    lower = 0
    for index, upper in enumerate(code_counts):
        if lower < count <= upper:
            return index
        lower = upper
    return None


def _bracket_other_columns(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    table: str,
    chain: list[tuple[int, list[str]]],
    other_columns: list[str],
    counts: dict[str, int],
    shapes: dict[str, str],
    schema: TargetSchema,
) -> dict[str, "_Row"]:
    """Bracket non-code columns into the chain, numbering every name winner.

    A candidate bijective with the level's code (an exact match) wins
    over a looser, repeats-tolerant one; admin level 0 is never resolved.
    """
    code_counts = [count for count, _cols in chain]
    bracketed: dict[int, list[str]] = {}
    for column in other_columns:
        index = _bracket_index(code_counts, counts[column])
        if index is not None:
            bracketed.setdefault(index, []).append(column)

    rows: dict[str, _Row] = {}
    for index, candidates in bracketed.items():
        level = index
        if level == 0:
            continue
        code_column = chain[index][1][0]
        winners = [
            c
            for c in candidates
            if shapes[c] == "name"
            and _containment_holds(conn, table, coarser=c, finer=code_column)
        ]
        exact = [
            c
            for c in winners
            if _containment_holds(conn, table, coarser=code_column, finer=c)
        ]
        resolved = exact or winners
        parent_code_column = chain[index - 1][1][0]
        for winner_index, column in enumerate(resolved):
            target = _numbered_target(schema.name_field, level, winner_index)
            unique_count = _combined_distinct_count(
                conn, table, parent_code_column, column
            )
            rows[column] = _Row(
                column,
                target,
                "",
                role="name",
                level=level,
                unique_count=unique_count,
            )
        for column in candidates:
            if column in resolved:
                continue
            unique_count = _combined_distinct_count(
                conn, table, parent_code_column, column
            )
            if column in winners:
                others = ", ".join(exact)
                rows[column] = _Row(
                    column,
                    None,
                    f"{CONFIDENCE_AMBIGUOUS}, level {level}; see {others}",
                    level=level,
                    unique_count=unique_count,
                )
            elif shapes[column] == "name":
                rows[column] = _Row(
                    column,
                    None,
                    f"{CONFIDENCE_AMBIGUOUS}, level {level}; repeats in group",
                    level=level,
                    unique_count=unique_count,
                )
            else:
                rows[column] = _Row(
                    column,
                    None,
                    f"{CONFIDENCE_AMBIGUOUS}, level {level}; shape unclear",
                    level=level,
                    unique_count=unique_count,
                )
    return rows


def main(conn: DuckDBPyConnection, name: str, schema: TargetSchema) -> None:  # noqa: C901
    """Discover a source file's admin hierarchy, writing crosswalk `{name}_02`."""
    table = f"{name}_01"
    columns = _candidate_columns(conn, table)
    shapes = _shape_classify(conn, table, columns)
    counts = _distinct_counts(conn, table, columns)
    _reclassify_constant_codes(conn, table, columns, shapes, counts)
    code_columns = [c for c in columns if shapes[c] == "code"]
    other_columns = [c for c in columns if c not in code_columns]

    code_groups = _build_code_groups(conn, table, code_columns, counts)
    chains = _chain_from_groups(conn, table, code_groups)
    chain = max(chains, key=len, default=[])

    rows: dict[str, _Row] = {}

    for index, (_count, cols) in enumerate(chain):
        level = index
        if level == 0:
            continue
        coarser = chain[index - 1][1][0]
        for column_index, column in enumerate(cols):
            target = _numbered_target(schema.code_field, level, column_index)
            unique_count = _combined_distinct_count(conn, table, coarser, column)
            rows[column] = _Row(
                column, target, "", role="code", level=level, unique_count=unique_count
            )

    chained_code_columns = {c for _count, cols in chain for c in cols}
    for column in code_columns:
        if column not in chained_code_columns:
            rows[column] = _Row(
                column,
                None,
                f"{CONFIDENCE_AMBIGUOUS}; doesn't fit chain",
                unique_count=counts[column],
            )

    other_rows = _bracket_other_columns(
        conn, table, chain, other_columns, counts, shapes, schema
    )
    rows.update(other_rows)

    for column in columns:
        if column not in rows:
            rows[column] = _Row(column, None, "", unique_count=counts[column])

    def sort_key(row: _Row, source_position: int) -> tuple[int, int, int, int]:
        if row.level is None:
            return (1, 0, 0, source_position)
        role_priority = 0 if row.role == "name" else 1
        return (0, -row.level, role_priority, source_position)

    position = {c: i for i, c in enumerate(columns)}
    entries = [(rows[c], position[c]) for c in columns]
    entries.sort(key=lambda pair: sort_key(*pair))

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" (
            column_order INTEGER, source_column VARCHAR, target_column VARCHAR,
            unique_count INTEGER, note VARCHAR
        )
    """)
    for i, (r, _pos) in enumerate(entries):
        conn.execute(
            f'INSERT INTO "{name}_02" VALUES (?, ?, ?, ?, ?)',
            [i, r.source_column, r.target_column, r.unique_count, r.note],
        )
