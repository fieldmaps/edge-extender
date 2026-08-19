"""Matches source columns to target-schema fields.

Exact/alias match first, then regex pattern match; for a repeatable
admin-level field (e.g. adm{n}_name), candidates matched by role but not a
literal level orders by COUNT(DISTINCT) and validates true hierarchical
nesting via a containment check before assigning a level, never guessing.
"""

from dataclasses import dataclass
from itertools import pairwise

from duckdb import DuckDBPyConnection

from topo_tools.core.duckdb_utils import quote_identifier
from topo_tools.core.schema_propose._constants import (
    CONFIDENCE_AMBIGUOUS,
    CONFIDENCE_EXACT,
    CONFIDENCE_NESTING_VALIDATED_RELATIVE,
    CONFIDENCE_PATTERN,
    CONFIDENCE_UNMATCHED,
)
from topo_tools.core.schema_propose._target_schema import TargetField, normalize

# fid/geom are topo-tools' own internal columns, never candidate source data.
_EXCLUDED_COLUMNS = {"fid", "geom"}


@dataclass
class _Row:
    source_column: str
    target_column: str | None
    confidence: str
    note: str | None


def _candidate_columns(conn: DuckDBPyConnection, table: str) -> list[str]:
    rows = conn.execute(f'DESCRIBE "{table}"').fetchall()
    return [r[0] for r in rows if r[0] not in _EXCLUDED_COLUMNS]


def _exact_match(
    column: str, fields: list[TargetField]
) -> tuple[TargetField, int | None] | None:
    """Match a column literally to a field's name/alias; level known if repeatable."""
    norm_col = normalize(column)
    for target_field in fields:
        if target_field.repeatable:
            lo, hi = target_field.repeatable
            for level in range(lo, hi + 1):
                if norm_col == normalize(target_field.name.format(n=level)):
                    return target_field, level
        elif norm_col in {
            normalize(c) for c in (target_field.name, *target_field.aliases)
        }:
            return target_field, None
    return None


def _role_match(column: str, target_field: TargetField) -> bool:
    """Check whether a column plausibly plays this field's role, level unknown."""
    if normalize(column) in {normalize(a) for a in target_field.aliases}:
        return True
    return any(p.search(column) for p in target_field.patterns)


def _order_and_validate(
    conn: DuckDBPyConnection, table: str, columns: list[str]
) -> tuple[list[str], bool]:
    """Order columns coarsest -> finest by COUNT(DISTINCT); validate true nesting.

    Returns (ordered_columns, all_valid). A tie or a failed containment
    check anywhere in the chain makes the whole set invalid: partial
    auto-resolution risks silently mis-assigning a level, so it's all
    flagged ambiguous together rather than split at the failure point.
    """
    counts = {
        c: conn.execute(
            f"SELECT COUNT(DISTINCT {quote_identifier(c)}) "
            f"FROM {quote_identifier(table)}"
        ).fetchone()[0]
        for c in columns
    }
    ordered = sorted(columns, key=lambda c: counts[c])
    valid = True
    for coarser, finer in pairwise(ordered):
        if counts[coarser] == counts[finer]:
            valid = False
            break
        bad = conn.execute(f"""--sql
            SELECT COUNT(*) FROM (
                SELECT {quote_identifier(finer)} FROM {quote_identifier(table)}
                GROUP BY {quote_identifier(finer)}
                HAVING COUNT(DISTINCT {quote_identifier(coarser)}) > 1
            )
        """).fetchone()[0]
        if bad > 0:
            valid = False
            break
    return ordered, valid


def _resolve_role_candidates(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    table: str,
    target_field: TargetField,
    candidates: list[str],
    own_level: int | None,
    rows: dict[str, _Row],
) -> None:
    if own_level is not None:
        lo, hi = target_field.repeatable
        if own_level not in range(lo, hi + 1):
            msg = (
                f"--own-level {own_level} is out of {target_field.name}'s "
                f"declared repeatable range ({lo}-{hi})"
            )
            raise ValueError(msg)

    if len(candidates) == 1:
        (only,) = candidates
        if own_level is not None:
            rows[only] = _Row(
                only,
                target_field.name.format(n=own_level),
                CONFIDENCE_EXACT,
                f"anchored via --own-level {own_level} "
                "(sole candidate for this role in this source)",
            )
        else:
            rows[only] = _Row(
                only,
                only,
                CONFIDENCE_NESTING_VALIDATED_RELATIVE,
                "sole candidate for this role in this source; "
                "assign the real admin level",
            )
        return

    ordered, valid = _order_and_validate(conn, table, candidates)
    if not valid:
        note = (
            f"matches the {target_field.name} role but its candidates "
            f"({', '.join(candidates)}) don't order into a single validated "
            "nesting chain (tie or failed containment check); cannot order "
            "automatically"
        )
        for c in candidates:
            rows[c] = _Row(c, c, CONFIDENCE_AMBIGUOUS, note)
        return

    n = len(ordered)
    for rank, column in enumerate(ordered, start=1):
        is_finest = rank == n
        if is_finest and own_level is not None:
            rows[column] = _Row(
                column,
                target_field.name.format(n=own_level),
                CONFIDENCE_EXACT,
                f"anchored via --own-level {own_level} "
                "(highest cardinality in the validated chain)",
            )
            continue
        relation = (
            f"coarser than {ordered[rank]}" if not is_finest else "finest in this chain"
        )
        rows[column] = _Row(
            column,
            column,
            CONFIDENCE_NESTING_VALIDATED_RELATIVE,
            f"rank {rank} of {n}, {relation}; assign the real admin level",
        )


def _pass_exact(
    columns: list[str],
    fields: list[TargetField],
    rows: dict[str, _Row],
    claimed: set[str],
) -> None:
    """Pass 1: literal canonical name, or an alias for a non-repeatable field."""
    for column in columns:
        match = _exact_match(column, fields)
        if match is None:
            continue
        target_field, level = match
        target = (
            target_field.name.format(n=level)
            if level is not None
            else target_field.name
        )
        rows[column] = _Row(column, target, CONFIDENCE_EXACT, None)
        claimed.add(column)


def _pass_role_nesting(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    table: str,
    columns: list[str],
    fields: list[TargetField],
    own_level: int | None,
    rows: dict[str, _Row],
    claimed: set[str],
) -> None:
    """Pass 2: role match per repeatable field, level resolved by nesting."""
    for target_field in fields:
        if not target_field.repeatable:
            continue
        candidates = [
            c for c in columns if c not in claimed and _role_match(c, target_field)
        ]
        if not candidates:
            continue
        claimed.update(candidates)
        _resolve_role_candidates(conn, table, target_field, candidates, own_level, rows)


def _pass_pattern(
    columns: list[str],
    fields: list[TargetField],
    rows: dict[str, _Row],
    claimed: set[str],
) -> None:
    """Pass 3: pattern match for non-repeatable fields still unclaimed."""
    for target_field in fields:
        if target_field.repeatable:
            continue
        for column in columns:
            if column in claimed:
                continue
            if any(p.search(column) for p in target_field.patterns):
                rows[column] = _Row(column, target_field.name, CONFIDENCE_PATTERN, None)
                claimed.add(column)
                break


def _pass_unmatched(columns: list[str], rows: dict[str, _Row]) -> None:
    """Pass 4: anything left matched nothing at all; retain as-is pending review."""
    for column in columns:
        if column not in rows:
            rows[column] = _Row(
                column,
                column,
                CONFIDENCE_UNMATCHED,
                "no canonical field matched; retaining original name pending review",
            )


def main(
    conn: DuckDBPyConnection,
    name: str,
    fields: list[TargetField],
    *,
    own_level: int | None = None,
) -> None:
    """Propose a source-column -> target-field crosswalk, writing `{name}_02`."""
    table = f"{name}_01"
    columns = _candidate_columns(conn, table)

    rows: dict[str, _Row] = {}
    claimed: set[str] = set()

    _pass_exact(columns, fields, rows, claimed)
    _pass_role_nesting(conn, table, columns, fields, own_level, rows, claimed)
    _pass_pattern(columns, fields, rows, claimed)
    _pass_unmatched(columns, rows)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" (
            column_order INTEGER, source_column VARCHAR, target_column VARCHAR,
            confidence VARCHAR, note VARCHAR
        )
    """)
    for i, c in enumerate(columns):
        r = rows[c]
        conn.execute(
            f'INSERT INTO "{name}_02" VALUES (?, ?, ?, ?, ?)',
            [i, r.source_column, r.target_column, r.confidence, r.note],
        )
