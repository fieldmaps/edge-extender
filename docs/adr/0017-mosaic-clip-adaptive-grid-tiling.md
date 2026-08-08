# 0017: Adaptive grid-tiling threshold and cell size, superseding ADR-0016's fixed constant

## Status

Accepted. Supersedes the fixed `CLIP_CELL = 1.0` decision in ADR-0016.

## Context

ADR-0016 fixed `CLIP_CELL = 1.0` degrees, applied unconditionally to every
parent fid, tuned against South Africa's single worst-case scenario (4,392
children, 281,369-vertex boundary). `topo-tools` is a general-purpose
package, not a single-run script: a fixed constant tiles every parent
identically regardless of actual complexity, paying subdivision overhead on
small/simple parents that never needed it, and giving no guarantee the same
constant stays fine-grained enough for a future parent more complex than
South Africa.

The 47-country Africa set gives a natural calibration range: vertex counts
span from Eswatini's 805 to South Africa's 281,369, and solving for the
`CLIP_TILE_TARGET_VERTICES` constant that reproduces ADR-0016's own
empirically-verified `cell=1.0` for South Africa's actual bbox (16.44° x
12.71°, 1350 target vertices/tile) generalizes smoothly across that range:
sparse, low-vertex-density countries like Chad and Niger solve to coarser
cells (~3.4-3.5°), dense small islands like Comoros solve to finer ones
(~0.26°).

## Decision

`core/clip.py::_subdivide_boundary` computes `ST_NPoints` on the parent
boundary before tiling. Below `CLIP_TILE_MIN_VERTICES` (5,000), it clips the
parent directly with no subdivision at all. Above that threshold,
`_adaptive_cell_size` solves the cell size from that parent's own vertex
density against its bbox area (`cell = sqrt(CLIP_TILE_TARGET_VERTICES *
bbox_area / vertex_count)`, clamped to `[CLIP_TILE_MIN_CELL,
CLIP_TILE_MAX_CELL]` = `[0.05, 5.0]` degrees), rather than reusing one fixed
value for every parent. All four constants live in `topo_tools/core/constants.py`.

## Consequences

Re-verified against both prior benchmarks: South Africa's own case (adaptive
cell solves to 1.001°, matching ADR-0016's hand-tuned 1.0° almost exactly)
reproduced 8.1s / 745MB peak RSS against ADR-0016's recorded 7.8s / 760MB.
The West Africa regression (8 countries, most below the 5,000-vertex
threshold and now skipping tiling entirely) still produced the identical
653 output rows / 0 issues. No full continent-scale rerun was done this
round; the West Africa regression plus the South Africa case (the two ends
of the complexity range already measured) were treated as sufficient
regression coverage given the formula is anchored on real, previously-
measured data rather than a new untested guess.
