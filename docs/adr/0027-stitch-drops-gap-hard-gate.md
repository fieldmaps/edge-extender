# 0027: stitch drops its gap hard gate, keeps the overlap one

## Status

Accepted.

## Context

`stitch`'s `_03_outputs.py` called the same shared `check_overlaps`/
`check_gaps` (`core/coverage.py`) every other tool's output stage uses,
raising `RuntimeError` on any interior hole in the union of its output.
That assumption holds for stitch's original use case, closing seams
between already-tiled pieces of the same complete layer, where any hole
really does mean a defect.

It broke down running `stitch` on a combined 111-of-315-country global
test file (assembled from `clip`'s multi-file batch output, see ADR-0023):
`check_gaps` correctly found interior holes, but almost all of them were
countries absent from the batch and fully enclosed by present neighbors,
not seam defects. `clean`'s own issue-detection stage on the same file
(`docs/adr/0026`'s regression run) found 18 such gaps; only 4 were
thin/sliver-shaped by Polsby-Popper classification, the rest large,
compact, non-thin holes. `stitch` has no such classification, and no
issues report to route tolerated gaps into the way `clean` does (see
"No coverage pre-check, no issues report" in `docs/explanation/stitch.md`)
, so its only option on a gap was fail the whole run.

## Decision

Removed the `check_gaps` call from `core/stitch/_03_outputs.py` entirely,
unconditionally, no flag, no thinness classification. Gaps in stitch's
output are not stitch's concern: whatever holes remain after the
whole-table `ST_CoverageClean` pass (`_02_clean.py`, unchanged) are
whatever the input's own coverage looked like, real seam or legitimate
absence, and stitch exports them either way. `check_overlaps` is
unchanged and still raises: two rows still occupying the same territory
is unambiguously wrong regardless of what the input was assembled from.

`match`, `mosaic`, and `extend` keep calling the same shared
`check_gaps` independently and are unaffected; their own use case (a
single already-tiled layer with a real gap-free-by-construction
guarantee) is exactly the case this gate protects.

## Consequences

`stitch`'s CLI/API contract no longer treats "gaps in the input reduce to
gaps in the output" as a failure. A caller that still wants stitch's old
strict behavior has no built-in way to get it back; nothing in the
codebase currently needs that. `tests/test_stitch.py`'s
`test_stitch_raises_on_real_gap` became
`test_stitch_tolerates_unclosed_gap`, asserting the run completes and
exports all 4 rows instead of raising.
