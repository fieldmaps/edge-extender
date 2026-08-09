# 0008: has_coverage_violations() alone cannot stand in for gap detection

## Status

Accepted

## Context

`_03_clean.py`'s fix-stage gate used to rely on `has_coverage_violations()`
alone to decide whether `ST_CoverageClean` was worth running at all.

## Decision

Verified empirically with a synthetic fixture (a pinwheel of 4 valid,
edge-matched polygons fully surrounding a real 1x1 hole):
`has_coverage_violations()` returned `False` even though a genuine
fully-enclosed gap existed. It only detects overlaps/mismatched edges,
never gaps, see
`docs/reference/shared.md`'s rule that this check must not be treated as a
gap check.

## Consequences

The old gate meant a gap-only input (no overlaps) was silently never fixed
despite being correctly reported in the issues file. The gate now also
checks whether any detected gap qualifies to fill under the resolved
`gap_maximum_width`, not just whether `has_coverage_violations()` is true.
