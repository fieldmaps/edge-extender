"""Structurally discovers a source file's admin hierarchy and code/name roles.

See docs/explanation/map.md and docs/adr/0054, 0064-0066 for the algorithm and why.
"""

from dataclasses import dataclass

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import is_noise_column
from topo_tools.core.duckdb_utils import quote_identifier
from topo_tools.core.map._constants import CONFIDENCE_AMBIGUOUS, CONFIDENCE_SUPPLEMENTAL
from topo_tools.core.map._target_schema import TargetSchema

# fid/geom are topo-tools' own internal columns, never candidate source data.
_EXCLUDED_COLUMNS = {"fid", "geom"}

_CODE_SHAPE_MAJORITY = 0.5


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
        if r[0] not in _EXCLUDED_COLUMNS and not is_noise_column(r[0])
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


def _embeds(conn: DuckDBPyConnection, table: str, child: str, parent: str) -> bool:
    """Check every non-null row has `child` contain `parent`, tolerating one sentinel.

    An all-null `parent`, or every failure sharing one `child` value, is no evidence.
    """
    evaluated_where = f"""
        {quote_identifier(child)} IS NOT NULL AND {quote_identifier(parent)} IS NOT NULL
    """
    not_contains = f"""
        NOT contains(
            CAST({quote_identifier(child)} AS VARCHAR),
            CAST({quote_identifier(parent)} AS VARCHAR)
        )
    """
    evaluated, bad = conn.execute(f"""--sql
        SELECT
            COUNT(*) FILTER (WHERE {evaluated_where}),
            COUNT(*) FILTER (WHERE {evaluated_where} AND {not_contains})
        FROM {quote_identifier(table)}
    """).fetchone()
    if bad == 0:
        return evaluated > 0
    culprits = conn.execute(f"""--sql
        SELECT DISTINCT CAST({quote_identifier(child)} AS VARCHAR)
        FROM {quote_identifier(table)}
        WHERE {evaluated_where} AND {not_contains}
    """).fetchall()
    if len(culprits) != 1:
        return False
    remaining = conn.execute(
        f"""--sql
        SELECT COUNT(*) FROM {quote_identifier(table)}
        WHERE {evaluated_where}
          AND CAST({quote_identifier(child)} AS VARCHAR) != ?
        """,
        [culprits[0][0]],
    ).fetchone()[0]
    return remaining > 0


def _looks_code_shaped(conn: DuckDBPyConnection, table: str, column: str) -> bool:
    """Check whether most non-null values contain a digit.

    Only consulted when no embedding evidence exists to pick code vs name.
    """
    digits, total = conn.execute(f"""--sql
        SELECT
            COUNT(*) FILTER (
                WHERE regexp_matches(
                    CAST({quote_identifier(column)} AS VARCHAR), '[0-9]'
                )
            ),
            COUNT(*) FILTER (WHERE {quote_identifier(column)} IS NOT NULL)
        FROM {quote_identifier(table)}
    """).fetchone()
    return total > 0 and digits / total > _CODE_SHAPE_MAJORITY


def _containment_holds(
    conn: DuckDBPyConnection, table: str, coarser: str, finer: str
) -> bool:
    """Check every `finer` maps to one `coarser`, tolerating one violating value."""
    violators = conn.execute(f"""--sql
        SELECT {quote_identifier(finer)} FROM {quote_identifier(table)}
        GROUP BY {quote_identifier(finer)}
        HAVING COUNT(DISTINCT {quote_identifier(coarser)}) > 1
    """).fetchall()
    return len(violators) <= 1


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


def _build_level_groups(
    conn: DuckDBPyConnection, table: str, columns: list[str], counts: dict[str, int]
) -> list[tuple[int, list[str]]]:
    """Group every column (code or name alike) by distinct count and bijection.

    A constant (single-value) column stays, a single-country file's admin0 can be one.
    """
    by_count: dict[int, list[str]] = {}
    for c in columns:
        by_count.setdefault(counts[c], []).append(c)

    groups: list[tuple[int, list[str]]] = []
    for count, cols in by_count.items():
        groups.extend(
            (count, cluster) for cluster in _cluster_by_bijection(conn, table, cols)
        )
    groups.sort(key=lambda g: g[0])
    return groups


def _cluster_by_bijection(
    conn: DuckDBPyConnection, table: str, cols: list[str]
) -> list[list[str]]:
    """Union same-count columns pairwise bijective with each other into one cluster."""
    parent = {c: c for c in cols}

    def find(c: str) -> str:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            if _bijective(conn, table, a, b):
                parent[find(a)] = find(b)

    clusters: dict[str, list[str]] = {}
    for c in cols:
        clusters.setdefault(find(c), []).append(c)
    return list(clusters.values())


def _build_chain(
    conn: DuckDBPyConnection, table: str, groups: list[tuple[int, list[str]]]
) -> list[tuple[int, list[str]]]:
    """Longest nesting path; a non-constant edge must be embedding-justified.

    See docs/adr/0066: a constant needs no embedding, anything else does,
    unless no candidate pair in the whole file embeds at all (docs/adr/0070).
    """
    n = len(groups)
    edges: dict[tuple[int, int], tuple[bool, bool]] = {}
    for finer_idx in range(n):
        _finer_count, finer_cols = groups[finer_idx]
        for coarser_idx in range(finer_idx):
            _coarser_count, coarser_cols = groups[coarser_idx]
            joins = all(
                _containment_holds(conn, table, coarser=a, finer=b)
                for a in coarser_cols
                for b in finer_cols
            )
            embeds = joins and any(
                _embeds(conn, table, b, a) for a in coarser_cols for b in finer_cols
            )
            edges[coarser_idx, finer_idx] = (joins, embeds)

    no_embedding_anywhere = not any(embeds for _joins, embeds in edges.values())

    best_len = [1] * n
    best_prev: list[int | None] = [None] * n
    for finer_idx in range(n):
        for coarser_idx in range(finer_idx):
            coarser_count, _coarser_cols = groups[coarser_idx]
            joins, embeds = edges[coarser_idx, finer_idx]
            if not joins:
                continue
            justified = coarser_count == 1 or embeds or no_embedding_anywhere
            if justified and best_len[coarser_idx] + 1 > best_len[finer_idx]:
                best_len[finer_idx] = best_len[coarser_idx] + 1
                best_prev[finer_idx] = coarser_idx
    if n == 0:
        return []
    end = max(range(n), key=lambda i: (best_len[i], len(groups[i][1]), groups[i][0]))
    chain_indices = []
    i: int | None = end
    while i is not None:
        chain_indices.append(i)
        i = best_prev[i]
    chain_indices.reverse()
    return [groups[i] for i in chain_indices]


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


def _assign_chain_roles(
    conn: DuckDBPyConnection,
    table: str,
    chain: list[tuple[int, list[str]]],
    schema: TargetSchema,
    counts: dict[str, int],
) -> dict[str, "_Row"]:
    """Assign every chain-level column a code/name role and numbered target.

    Embeds the resolved parent, or looks code-shaped -> code; else -> name.
    """
    rows: dict[str, _Row] = {}
    for index, (count, cols) in enumerate(chain):
        if count == 1:
            continue
        level = index
        parent_cols = chain[index - 1][1] if index > 0 else []
        embeds_parent = {
            c: any(_embeds(conn, table, c, p) for p in parent_cols) for c in cols
        }
        roles: dict[str, str] = {
            c: "code"
            if embeds_parent[c] or _looks_code_shaped(conn, table, c)
            else "name"
            for c in cols
        }
        parent_code = parent_cols[0] if parent_cols else None
        for role, template in (
            ("code", schema.code_field),
            ("name", schema.name_field),
        ):
            members = [c for c in cols if roles[c] == role]
            for member_index, column in enumerate(members):
                target = _numbered_target(template, level, member_index)
                unique_count = (
                    counts[column]
                    if parent_code is None
                    else _combined_distinct_count(conn, table, parent_code, column)
                )
                rows[column] = _Row(
                    column,
                    target,
                    "",
                    role=role,
                    level=level,
                    unique_count=unique_count,
                )
    return rows


def _bracket_level(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    table: str,
    chain: list[tuple[int, list[str]]],
    level: int,
    candidates: list[str],
    counts: dict[str, int],
    schema: TargetSchema,
    chain_rows: dict[str, "_Row"],
) -> dict[str, "_Row"]:
    """Resolve one bracketed level's candidates into name/supplemental/ambiguous rows.

    A winner is `name` only if the level has no chain name yet, else `supplemental`.
    """
    code_column = chain[level][1][0]
    winners = {
        c
        for c in candidates
        if _containment_holds(conn, table, coarser=c, finer=code_column)
    }
    level_has_name = any(
        chain_rows[m].role == "name" for m in chain[level][1] if m in chain_rows
    )
    parent_code_column = chain[level - 1][1][0] if level > 0 else None

    def unique_count_for(column: str) -> int:
        if parent_code_column is None:
            return counts[column]
        return _combined_distinct_count(conn, table, parent_code_column, column)

    rows: dict[str, _Row] = {}
    winner_index = 0
    for column in candidates:
        unique_count = unique_count_for(column)
        if column not in winners:
            rows[column] = _Row(
                column,
                None,
                f"{CONFIDENCE_AMBIGUOUS}, level {level}",
                level=level,
                unique_count=unique_count,
            )
        elif level_has_name:
            rows[column] = _Row(
                column,
                None,
                f"{CONFIDENCE_SUPPLEMENTAL}, superset of level {level}",
                level=level,
                unique_count=unique_count,
            )
        else:
            target = _numbered_target(schema.name_field, level, winner_index)
            winner_index += 1
            rows[column] = _Row(
                column,
                target,
                "",
                role="name",
                level=level,
                unique_count=unique_count,
            )
    return rows


def _bracket_other_columns(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    table: str,
    chain: list[tuple[int, list[str]]],
    other_columns: list[str],
    counts: dict[str, int],
    schema: TargetSchema,
    chain_rows: dict[str, "_Row"],
) -> dict[str, "_Row"]:
    """Bracket non-chain columns into the chain by cardinality range."""
    code_counts = [count for count, _cols in chain]
    bracketed: dict[int, list[str]] = {}
    for column in other_columns:
        index = _bracket_index(code_counts, counts[column])
        if index is not None:
            bracketed.setdefault(index, []).append(column)

    rows: dict[str, _Row] = {}
    for level, candidates in bracketed.items():
        if chain[level][0] == 1:
            continue
        rows.update(
            _bracket_level(
                conn, table, chain, level, candidates, counts, schema, chain_rows
            )
        )
    return rows


def main(conn: DuckDBPyConnection, name: str, schema: TargetSchema) -> None:
    """Discover a source file's admin hierarchy, writing crosswalk `{name}_02`."""
    table = f"{name}_01"
    columns = _candidate_columns(conn, table)
    counts = _distinct_counts(conn, table, columns)

    # An all-null column has no evidence either way, same principle as _embeds().
    chainable_columns = [c for c in columns if counts[c] > 0]
    level_groups = _build_level_groups(conn, table, chainable_columns, counts)
    chain = _build_chain(conn, table, level_groups)

    rows = _assign_chain_roles(conn, table, chain, schema, counts)

    chained_columns = {c for _count, cols in chain for c in cols}
    other_columns = [c for c in columns if c not in chained_columns]

    other_rows = _bracket_other_columns(
        conn, table, chain, other_columns, counts, schema, rows
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
