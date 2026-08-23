# 0062: `map` adds a `unique_count` column, drops `note` for resolved rows

## Status

Accepted.

## Context

ADR-0061 dropped level from a resolved row's `note` but kept the tier
word (`"code"`, `"name"`); a real crosswalk review flagged that word as
redundant too, since the row's presence and `target_column` already say
what it is. Separately, the previous prefix-based "nest confirmed"
percentage (ADR-0060) was dropped for adding no correctness information
beyond what the chain-building containment check (`_containment_holds`)
already guarantees.

That containment check only verifies a code's *own* values map 1:1 to
their parent; it says nothing about whether a name (or a code) is
reused verbatim under two different parents (e.g. "County 1" appearing
in both Province A and Province B) with no signal exposed anywhere that
this happened, since the raw distinct count alone can't distinguish "2
provinces, 1 shared county name" from "2 provinces, 2 real counties
sharing a name".

## Decision

1. `map`'s crosswalk CSV gains a fourth column, `unique_count`. For any
   row bracketed to a level (`code`, `name`, or `ambiguous` with a
   level), it's `COUNT(DISTINCT parent_code, this_column)` against the
   level directly above it, computed via `_combined_distinct_count()`.
   For any other row (level 0, a code-shaped column outside the chain,
   or fully `unmatched`), it's the column's own `COUNT(DISTINCT)`
   (already available in `counts`), so every row's `unique_count` is
   populated, not just the resolved ones.
2. A `code`/`name` row's `note` is now empty; the tier word retained by
   ADR-0061 is dropped too, since `unique_count` carries the signal a
   reviewer actually needs. An `ambiguous` row's `note` is unchanged
   from ADR-0061 (tier, level, one short clause).
3. The crosswalk CSV is `source_column`, `target_column`, `unique_count`,
   `note`, four columns instead of three.

## Consequences

A reviewer compares `unique_count` against the column's row count (or
against a sibling candidate's `unique_count` at the same level) to spot
a name/code that looks resolved but is only locally unique, something
neither the dropped percentage nor a bare tier word could show. Losing
candidates at a level (the ones that lost to an exact match) also carry
`unique_count`, so a reviewer can compare the winner's cardinality
against what it beat.
