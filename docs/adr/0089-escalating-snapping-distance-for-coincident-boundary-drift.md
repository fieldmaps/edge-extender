# 0089: escalating snapping_distance for coincident-boundary clip drift

## Status

Accepted.

## Context

`edge-mosaic`/`edge-match` on a real Haiti admin3-into-admin0 clip raised
`INVALID_EDGES` in `edge-stitch`'s final output. Root-caused via direct
`ST_CoverageClean`/`ST_CoverageInvalidEdges_Agg` inspection: two adjacent
admin3 units share an internal border that runs coincident with Haiti's
own coastline (the parent boundary) for roughly 40m, not just touching
it at one point; every vertex on that stretch measured 0.000m from the
parent boundary curve. `core/edge_clip/_engine.py` clips each child
independently (`ST_Intersection(child, parent)`, one GEOS call per
child), and GEOS's `OverlayNG` engine makes its own, separately-computed
snap-rounding decisions along that degenerate coincident-edge stretch
per call. The two children ended up keeping different vertex subsets
there (one even gained a vertex neither input had), producing a
few-meter mismatch. This reproduced identically with zero tiling, and
the raw pre-clip input had zero invalid edges and zero gaps, ruling out
both `core/edge_clip/_tiling.py`'s grid decomposition and dirty source
data as the cause. Pre-snapping each child onto the parent boundary
before clipping, and inserting the exact boundary-crossing vertex that
already existed byte-identically in both children pre-clip, were also
tested directly and neither prevented the divergence: the mismatch is
introduced by each independent `ST_Intersection` call's internal
floating-point processing of the *rest* of that child's geometry, not by
a missing or underdetermined vertex at the crossing itself.

`edge-stitch`'s whole-table `ST_CoverageClean` pass
(`core/edge_stitch/_02_clean.py`) is the one place designed to
reconcile exactly this kind of independent-computation seam, but its
`snapping_distance` was hardcoded to `SNAP_TOLERANCE` (~1.1mm),
calibrated against raw source-data digitization noise (ADR-0002/0029/
0040), several orders of magnitude too tight for this artifact.

Tested directly against the failing case: `snapping_distance=2e-8`
(one `SNAP_TOLERANCE` step above the default) already resolved it, and
the whole range from 2e-8 up to 1e-3 resolved it. Comparing the 1e-8 vs.
2e-8 outputs showed only 3 of 570 fids differing at all, by a
symmetric-difference area of ~0.03m² each, confirming the fix is
localized to the actual defect. A single fixed replacement constant
would have worked for this case, but has no principled ceiling: the
drift magnitude scales with how closely-spaced the input vertices
happen to be (this case had an 8cm near-duplicate vertex pair sitting in
an otherwise 1.5-16m spaced stretch), so a value tuned to Haiti isn't
guaranteed sufficient for a denser input elsewhere.

## Decision

`core/coverage.py` gains `coverage_clean_escalating()`: it calls
`coverage_clean()` at `SNAP_TOLERANCE` first (identical to today's
behavior for every already-valid layer), and only if
`ST_CoverageInvalidEdges_Agg` still flags the result does it retry,
adding `SNAP_ESCALATION_STEP` (= `SNAP_TOLERANCE`) linearly per attempt
rather than multiplying, up to `SNAP_ESCALATION_MAX_STEPS` (9, capping
the ceiling at 1e-7 deg, ~1.1cm). `core/edge_stitch/_02_clean.py` calls
this instead of `coverage_clean()` directly; no other `coverage_clean()`
call site changed. `edge-mosaic` and `edge-match` both call
`core.edge_stitch`'s stage function directly, so both benefit with no
change of their own. `topo-clean`'s own `coverage_clean` call
(`core/topo_clean/_03_clean.py`) keeps its existing, more elaborate
post-clean validation and caller-configurable `--snapping-distance`,
out of scope here; `edge-extend`'s merge-stage call
(`core/edge_extend/_05_merge.py`) isn't independently clipping
separately-computed pieces the way `edge-clip` does per-parent-fid, so
it isn't exposed to this failure mode.

## Consequences

A layer with no coincident-boundary drift is unaffected: the first,
default-tolerance attempt succeeds and no retry happens. A layer that
hits this defect gets progressively wider `snapping_distance` attempts,
each a full whole-table `ST_CoverageClean` pass, until one resolves it
or the loop exhausts at 1e-7 deg and falls through to the existing
`check_valid_topology` raise in `edge_stitch/_03_outputs.py`, unchanged
from before this decision.
