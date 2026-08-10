# 0038: stitch's gap gate restored at the noise floor

## Status

Accepted.

## Context

`docs/adr/0027` removed `stitch`'s gap hard gate entirely (`check_invalid_edges`
alone, no `check_gaps`/`check_valid_topology`) because at the time `stitch`
had no issues-report machinery: raising on every leftover gap, including
wide, legitimate ones, would crash the tool on its own normal output with
no way to surface a narrower, genuine defect separately. That's no longer
true: `stitch/_03_outputs.py` gained `_build_issues()` and a `kind='gap'`
issues report since, mirroring `match`/`mosaic` (`docs/adr/0035`,
`docs/adr/0036`). `match`/`mosaic` both call `check_valid_topology()` with
`max_gap_width=SNAP_TOLERANCE`, raising only on a gap at or below the
noise floor and tolerating (but still reporting) a wider one.

`stitch`'s own seam gaps documented in `docs/explanation/stitch.md` run
from slivers up to ~645m (Burundi's admin2-into-admin1 case), far above
`SNAP_TOLERANCE` (~1.1mm): restoring a `SNAP_TOLERANCE`-bounded gate would
never reintroduce ADR-0027's original false-positive problem, since real
seam-closing work always leaves either nothing or a wide gap, not a
noise-level one.

## Decision

`stitch/_03_outputs.py` now calls `check_valid_topology(conn,
f"{name}_02", max_gap_width=SNAP_TOLERANCE)`, the same call `match`/`mosaic`
make, replacing the `check_invalid_edges()`-only call ADR-0027 left in
place.

## Consequences

`stitch` now raises on a leftover gap at or below `SNAP_TOLERANCE` (a
genuine coverage-clean failure to close seam noise), not just on invalid
edges. The existing `_build_issues()`/remaining-gap warning are
unchanged, they still report and log any wider gap without raising.
