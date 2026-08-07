# 0011: Two overlap-detection bugs found profiling clean at portolan scale

## Status

Accepted

## Context

Profiling `_02_issues.py`'s `_build_overlaps` against real admin-boundary
layers (`--debug`, Apple Silicon/10 logical cores) surfaced two bugs, both
only visible past a few thousand fids.

## Decision

1. **Overlap join predicate was `ST_Intersects`, not `ST_Overlaps`/
   `ST_Contains`.** `ST_Intersects` is true for any pair of polygons that
   merely share a boundary edge -- the normal case for every adjacent pair
   in a coverage layer, not a defect. On Indonesia admin3 (7,069 fids) this
   matched 18,457 candidate pairs, each still paying for `ST_Intersection`
   + `ST_MakeValid` + `ST_CollectionExtract`, and the stage did not finish
   in 6+ minutes. Switched the join predicate to `ST_Overlaps(a, b) OR
   ST_Contains(a, b) OR ST_Contains(b, a)` -- `ST_Overlaps` alone would
   miss a fully-duplicated or nested polygon pair (OGC: its intersection
   equals one/both inputs, so `ST_Overlaps` is false by definition), hence
   the `ST_Contains` half. Regression test:
   `test_clean_detects_full_containment_overlap` in `tests/test_clean.py`.
2. **Self-joining the wide `_01` table (36 columns for real admin data)
   instead of a narrow `(fid, geom)` projection made DuckDB fall back to
   near-single-threaded execution**, even though the join only references
   `fid`/`geom`. Confirmed on Indonesia admin3: the join against `_01` ran
   at ~99% CPU; the identical join against a narrow projection of the same
   rows ran at ~420% CPU. `_build_overlaps` now always projects to
   `{table}_narrow` before joining.

## Consequences

Both fixes are permanent; any new join added to `_build_overlaps` (or a
similar detection query) must use the correct overlap predicate and join
against a narrow projection, not the wide input table.
