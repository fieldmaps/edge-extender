# 0002: ST_CoverageClean's gap_maximum_width has no GEOS-native auto-fill default

## Status

Accepted

## Context

Needed to know whether omitting `gap_maximum_width` would auto-fill gaps
sensibly, the way `snapping_distance` has a real computed auto-default
(`extent_diameter / 1e8`).

## Decision

Verified against upstream source (duckdb-spatial's `geos_module.cpp`, GEOS's
`CoverageCleaner.h`/`.cpp`): the C++ class member is hardcoded to `0.0`, and
a negative/omitted value is a no-op that leaves it there. `clean`'s
`--gap-width auto` mode therefore computes an explicit width itself, from the
widest thin detected gap; `all` mode uses a fixed
`GAP_MAXIMUM_WIDTH_ALL_DEG = 360` sentinel.

## Consequences

Confirmed safe across the full `0`-`360°` range on real defect data (see
`docs/adr/0003-st-coverageclean-positional-args.md` for the sweep that
validated this). A future DuckDB spatial upgrade should re-verify this
against the new source before assuming the behavior is unchanged.
