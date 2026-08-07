# 0009: clean's area-sanity floor is anchored to detected overlap area, not dataset size

## Status

Accepted

## Context

An earlier version of the total-area floor was a flat fraction of the whole
input area (`output_area >= input_area * AREA_SANITY_FACTOR`, `0.8`).
Tightening that fraction to `0.95` broke real, intentional tests: resolving
a single overlap that's a large fraction of a *small* dataset's total area
can legitimately cost 12-19% of the total -- indistinguishable, as a flat
fraction, from real corruption on a *large* dataset where the same kind of
defect is a tiny fraction of total. A flat fraction of dataset size can't
tell those two cases apart because it isn't looking at the defect at all.

## Decision

The floor now scales with what was actually detected:

```
min_area = input_area * (1 - AREA_NOISE_FACTOR) - overlap_area * OVERLAP_LOSS_HEADROOM
```

- `AREA_NOISE_FACTOR = 0.02` bounds baseline loss when **no** overlaps are
  detected -- double the ~1% per-fid renoding drift confirmed on real
  defect-dense data.
- `overlap_area` is `SUM(ST_Area(geom))` over `{name}_02`'s `kind =
  'overlap'` rows.
- `OVERLAP_LOSS_HEADROOM = 3.0` allows resolving an overlap to cost up to
  3x its own detected footprint -- `ST_CoverageClean` can redraw a fid's
  boundary well beyond the immediate overlap it's resolving, confirmed up
  to ~1.5x on a real regression case.

## Consequences

Verified against real portolan admin-boundary files spanning zero, tiny,
and moderate overlap counts (`mex/adm2`, `egy/adm3`, `khm/adm3`,
`cod/adm2`) -- no false rejections, and the small-dataset tests that
originally motivated a loose floor still pass with real headroom to spare.
