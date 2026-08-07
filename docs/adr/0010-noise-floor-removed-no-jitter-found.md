# 0010: clean's floating-point noise floor was removed after finding no native jitter

## Status

Accepted

## Context

An earlier version discarded any detected gap/overlap below
`MIN_ISSUE_AREA_M2` (`1e-4 m^2`, ~1cm^2), ported directly from
topo-tools-js's own noise floor -- itself sized to a float-jitter magnitude
(up to `1.6e-7 m^2`) observed in that app's WASM-compiled GEOS build, never
independently measured against this native pipeline.

## Decision

Verified directly: ran this pipeline's exact gap- and overlap-detection
queries with the floor removed against five real/synthetic already-clean
inputs -- two hand-built synthetic fixtures, a real 9,658-fid COD admin4
layer, and Chile/Philippines/Indonesia admin3's `extended.parquet`
(full-pipeline output, each confirmed `has_coverage_violations() == False`)
-- and found zero floating-point artifacts on either detection path. The
overlap join predicate (`ST_Overlaps`/`ST_Contains`) never matched a
candidate pair on any of these valid coverages, since it requires true
interior intersection, not mere boundary-touching, so `ST_Intersection`
never even ran on a real candidate.

## Consequences

The noise floor was removed; `clean` now reports every detected gap and
overlap regardless of size. Consistent with `docs/explanation/change.md`'s
documented WASM-only GEOS `OverlayNG` bug that doesn't reproduce natively --
constants tuned against topo-tools-js's WASM-compiled GEOS build don't
necessarily carry over to this native pipeline without independent
verification.
