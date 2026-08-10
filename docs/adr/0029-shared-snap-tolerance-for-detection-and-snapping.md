# 0029: has_coverage_violations and internal snapping_distance now share one fixed SNAP_TOLERANCE

## Status

Accepted

## Context

`has_coverage_violations()` (`core/coverage.py`) checked
`ST_CoverageInvalidEdges_Agg(geom)` at the default tolerance of `0`. Repro:
two unit squares separated by a 1e-10° gap (floating-point-noise scale)
returned `has_coverage_violations() == False` *and* `ST_Intersects() ==
False` in `extend/_02_lines.py`'s neighbor-union join, so `_02_lines.py`
treated the entire shared boundary as pure exterior edge on both sides,
corrupting Voronoi seeding/extension along what should be an invisible
internal edge.

Separately, even where a violation IS flagged, the three internal
`coverage_clean` call sites (`extend/_01_inputs.py`, `extend/_05_merge.py`,
`stitch/_02_clean.py`) left `snapping_distance` on DuckDB's dynamic,
extent-relative auto-default (`extent_diameter / 1e8`) rather than pinning
it. Measured on real small-territory test files, this default undershoots
`SNAP_TOLERANCE` (i.e. is *tighter*, not looser): `sxm_admin1` 1.53e-09
(6.5x too tight), `maf_admin0` 3.83e-09 (2.6x), `grd_admin1` 6.91e-09
(1.4x), `vct_admin1` 9.20e-09 (1.1x). A violation newly flagged at
`SNAP_TOLERANCE` could therefore fail to actually close on files like
these.

## Decision

Pass `SNAP_TOLERANCE` as the tolerance arg to `ST_CoverageInvalidEdges_Agg`.
Verified: at `tolerance=SNAP_TOLERANCE` the 1e-10° repro gap is correctly
flagged `True`, while a real 1e-6° gap (100x larger) correctly stays
`False`.

Also pinned `snapping_distance=SNAP_TOLERANCE` explicitly at all three
internal `coverage_clean` call sites, replacing the dynamic auto-default.
Confirmed `extend` still runs clean end-to-end on `sxm_admin1` (the worst
case above) after the fix.

## Consequences

Noise-scale gaps between adjacent polygons in raw input are now caught and
closed at import time instead of silently corrupting downstream Voronoi
extension. `has_coverage_violations`'s existing gap-blindness
(`docs/adr/0008-has-coverage-violations-misses-gaps.md`) is unchanged, this
only affects edge-mismatch detection, not enclosed real holes.
