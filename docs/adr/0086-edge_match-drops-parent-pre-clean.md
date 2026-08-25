# 0086: `edge-match` drops its parent/clip layer pre-clean

## Status

Accepted.

## Context

Real-data testing against the fieldmaps global admin0 file (~730 MB, 195+
countries) showed `edge-match`'s background run stalled for 24+ minutes
inside `core/edge_match/_01_inputs.py`'s `load_and_clean_parent()`, before
assignment even started. That function called
`core.io.read_reproject_and_clean()`, running a zero-tolerance
(`gap_maximum_width=0`) `has_valid_topology()` check plus a conditional
`ST_CoverageClean` on the parent/clip layer.

`edge-mosaic`'s `load_parent()` (`core/assign/_inputs.py`) loads the same
kind of parent/clip layer raw, with no such check. ADR-0018 removed this
exact class of check from `edge-mosaic` for this exact reason: a single
huge admin0 polygon (Canada/USA-scale) made it pathological (>66 minutes,
non-terminating), and it was fully redundant with the final output's hard
gate, which already raises on any real overlap/gap defect.

`edge-match`'s parent role is architecturally identical to `edge-mosaic`'s:
a clip boundary, never itself extended. Nothing downstream (`_02_groups.py`,
`_03_clip.py`, `_04_stitch.py`) relies on the parent being pre-cleaned; the
underlying `core.edge_clip`/`core.assign` engine already runs against a
raw, uncleaned parent for `edge-mosaic` and standalone `edge-clip` in
production. The one documented rationale for pre-cleaning the parent (a
shared, exact parent boundary giving vertex-identical adjacent edges,
`docs/explanation/edge_match.md`'s rejected `ST_Snap` experiment) was
tested there and found to make zero measurable difference: seam quality
comes from `edge-stitch`'s own whole-table `ST_CoverageClean`, not from
parent vertex identity.

## Decision

`core/edge_match/_01_inputs.py`'s `load_and_clean_parent()` is removed.
`main()` now loads the parent via `core.assign.load_parent()`, the same
raw loader `edge-mosaic` already uses, instead of
`read_reproject_and_clean()`. `load_and_clean_child()` is unchanged: the
child still needs the same zero-tolerance pre-clean `edge-extend` uses
before Voronoi extension.

## Consequences

`edge-match`'s parent load is now comparable in cost to `edge-mosaic`'s
(a plain read/reproject, no coverage check), instead of stalling on large
real-world parent files. The final output's hard gate
(`check_valid_topology` in `_05_outputs.py`) remains the sole correctness
guarantee for the parent role, matching `edge-mosaic`'s design.
