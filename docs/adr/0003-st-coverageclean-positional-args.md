# 0003: Call ST_CoverageClean positionally, never with DuckDB's `:=` named-argument syntax

## Status

Accepted

## Context

`coverage_clean()` (`core/coverage.py`) previously built its `ST_CoverageClean`
call with conditional named arguments (appending `snapping_distance := ...`
only when set). Two symptoms appeared: narrow, non-monotonic invalid-edges/
`TopologyException` failures at specific gap widths, and silent area erosion
at wide widths. These were misdiagnosed as two independent `ST_CoverageClean`
instabilities and worked around with `_03_clean.py`'s
`GAP_WIDTH_ESCALATION_FACTORS` retry ladder.

## Decision

Root cause: DuckDB binds named arguments to compiled/extension scalar
functions purely by position, silently discarding the name (filed upstream
as duckdb/duckdb#24574). The conditional named-arg construction shifted a
caller-supplied `gap_maximum_width` into the `snapping_distance` slot
whenever `snapping_distance` was left at `auto`/`None` — `clean`'s default.
Fixed by switching `coverage_clean()` to a fully positional call (`geoms,
snapping_distance, gap_maximum_width`, using `-1` for an omitted value).

## Consequences

Both symptoms vanished, confirmed by sweeping `gap_maximum_width` from
`1e-6` to `360°` against the real 164-fid/190km² admin-boundary layer that
originally exhibited both symptoms — flat, monotonic area, zero invalid
edges throughout. The escalation ladder (`GAP_WIDTH_ESCALATION_FACTORS`) was
removed; `_03_clean.py` now makes a single `ST_CoverageClean` call, validated
by `has_coverage_violations()`, a total-area sanity floor, a per-fid erosion
check, and a geometry-type check, raising immediately if any fails. Never
reintroduce named-argument calls to compiled/extension DuckDB functions.
