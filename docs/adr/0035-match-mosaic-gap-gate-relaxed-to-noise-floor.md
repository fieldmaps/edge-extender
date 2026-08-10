# 0035: match/mosaic's gap hard gate relaxes to a noise floor

## Status

Accepted.

## Context

`match`/`mosaic`'s `_05_outputs.py`/`_03_outputs.py` called the shared
`check_valid_topology()` (`core/coverage.py`) with its default, zero-
tolerance gap check: any interior hole in the union of the final output,
of any size, raised `RuntimeError`.

That's correct for `extend`: it has no parent/clip layer, its whole job
is guaranteeing a complete coverage of its own footprint, so any gap
really is a bug.

It breaks for `match`/`mosaic`: they clip children against a parent/clip
layer whose own shape can have a real, legitimate interior hole. South
Africa's admin0 boundary has one for Lesotho, a country fully enclosed by
South African territory. Matching South Africa's admin4 into South
Africa's own admin0 boundary correctly reproduces that hole in the
output, and the zero-tolerance gate raised over it. `match`/`mosaic` have
no way to tell that case apart from a real coverage defect by size alone,
both can be wide, so treating every gap as fatal meant a legitimately-
shaped clip layer could never be used at all.

This is the same class of problem ADR-0027 already solved for `stitch` (a
hole might be a legitimate absence, not a defect), just for a different
underlying cause: `stitch` sees gaps from an incompletely-batched tiling
run, `match`/`mosaic` see them from the parent layer's own real shape.

## Decision

`match`/`mosaic` now call `check_valid_topology(conn, table,
max_gap_width=SNAP_TOLERANCE)`: still raises on any overlap or mismatched
edge, and still raises on a gap at or below `SNAP_TOLERANCE` (nothing
that small should ever survive the pipeline's own noise-floor cleaning
passes, so a leftover one is unambiguously a bug), but no longer raises
on a wider one.

A wider leftover gap is not silently dropped: `match`/`mosaic` add a
`kind='gap'` row (width, area, thinness ratio) to their existing issues
report for each one, and log a warning naming the count, so a human can
review whether it's a real parent-layer hole or something worth
investigating. `count_gaps()` (`core/coverage.py`, new) supplies the
count; `gap_geometries_sql()` (also new, factored out of `detect`'s own
gap-detection query) supplies the individual hole geometries for the
issues rows.

`extend` is unaffected: its call to `check_valid_topology()` keeps the
default `max_gap_width=None`, unchanged strict behavior, since it has no
parent/clip layer and no equivalent legitimate-hole case.

## Consequences

`match`/`mosaic` no longer crash on a parent/clip layer with a real
enclosed-country hole; the same behavior change also means a genuinely
too-wide unclosed seam (one `SNAP_TOLERANCE` can't explain away) no
longer aborts the run either, it's now a warning plus an issues-report
row instead of a hard failure. A caller relying on the old strict
behavior to catch a wide seam defect must now check the issues report
rather than trust that the call would have raised. `tests/test_match.py`/
`tests/test_mosaic.py` gained fixtures for both the tolerated-enclave
case and the still-raising micro-gap case (see `docs/reference/match.md`,
`docs/reference/mosaic.md`, `docs/reference/shared.md`).
