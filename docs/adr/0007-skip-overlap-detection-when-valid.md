# 0007: Skip overlap detection when the coverage is already valid

## Status

Accepted

## Context

`_02_issues.py`'s `_build_overlaps` (bbox-prefiltered O(n^2) self-join) was
the dominant cost of a `clean` run on an already-clean dataset -- confirmed
on a real 9,658-fid admin4 layer: the full `clean` CLI run took ~20 minutes
even though the input had zero defects, because overlap detection ran
unconditionally regardless of whether anything was actually wrong.

## Decision

`main()` now checks `has_coverage_violations()`
(`ST_CoverageInvalidEdges_Agg`, the shared `core/coverage.py`) before
running `_build_overlaps`, and writes an empty overlaps table directly when
it's already `False` -- a coverage with no invalid edges cannot contain an
overlapping or nested pair either.

Gap detection (`_build_gaps`) still always runs regardless -- unlike
overlaps, there's no cheaper GEOS primitive that answers "are there any
gaps" without doing the same whole-table union `_build_gaps` itself needs to
actually extract them. An earlier attempt added a separate `has_gaps()`
pre-check ahead of `_build_gaps` to decide whether to skip it too; that
pre-check computed its own whole-table union just to return a boolean,
which `_build_gaps` then recomputed from scratch whenever gaps actually
existed -- paying for the union twice with no benefit. Letting `_build_gaps`
run unconditionally avoids that duplication and costs the same as the union
alone.

## Consequences

~5s on the 9,658-fid layer for overlap detection, versus minutes for the
equivalent self-join. Gap detection costs ~18s on the same layer, giving
~23s total for a fully clean dataset, without a wasted extra union on a
dataset that actually has gaps.
