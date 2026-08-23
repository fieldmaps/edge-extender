# 0060: `map` drops the `confidence` column, trims `note` to essentials

## Status

Accepted.

## Context

The crosswalk CSV carried both a `confidence` column and a verbose `note`
column, the latter spelling out chain rank, "the real admin level" hedging
language, and internal algorithm detail (e.g. "a function of this level's
code") a reviewing human doesn't need to act on the row. User direction:
drop the `confidence` column, fold its value into `note`, and cut `note`
down to the minimum that still tells a reviewer what happened.

## Decision

1. The `confidence` column is removed; a resolved row's `note` starts with
   its tier (`code`, `name`, `ambiguous`) and level, e.g. `"code, level 1"`.
2. `note` keeps at most one short clause beyond that: a nest-confirmation
   rate for a code row only when it's below 100%, the exact-match column's
   name for an ambiguous row that lost to one, `"repeats in group"` or
   `"shape unclear"` for the other two ambiguous cases, `"doesn't fit
   chain"` for a code-shaped column outside the chain.
3. An `unmatched` row's `note` is empty, same as its `target_column`.

## Consequences

The crosswalk CSV is three columns (`source_column`, `target_column`,
`note`) instead of four. A reviewer scans `note` for the tier and reason
in one line instead of a full sentence; the dropped detail (rank-of-N
phrasing, "assign the real admin level", "a function of this level's
code") was internal algorithm narration, not something a review decision
depended on.
