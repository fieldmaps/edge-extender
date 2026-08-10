# 0037: clean's gap gate is bounded by its own fill target

## Status

Accepted.

## Context

`clean/_03_clean.py`'s post-fix validation raised on any invalid edge,
area loss, unrelated-fid collapse, or bad geometry type, but never on a
leftover gap: `clean` can legitimately leave gaps unfilled by design (the
default mode only fills when a gap was detected, `--maximum-gap-width
thin` skips a compact/non-thin gap, or a numeric cap can be narrower than
some detected gap), so a blanket gap gate would make the tool crash on
its own default behavior. `_04_outputs.py`'s later `check_invalid_edges`
re-check catches invalid edges, but a floating-point-scale gap narrower
than what `clean` actually asked `ST_CoverageClean` to close is not by
design, it's `ST_CoverageClean` failing to do the job it was given.

## Decision

`_03_clean.py`'s post-fix validation now also raises if the output has an
unfilled gap at or below `gap_maximum_width_deg`, the width actually
requested for this run (`has_gaps(conn, out_table,
max_width=gap_maximum_width_deg)`), skipped entirely when
`gap_maximum_width_deg is None` (no fill was requested at all). A gap
left wider than the requested width is unaffected, still only logged,
never raised on.

## Consequences

`clean` now catches a real coverage-clean under-fill (asked to close a
gap up to width X, a gap at or below X remains) as a hard failure instead
of a silently-logged warning indistinguishable from a legitimate
by-design leftover gap. `tests/test_clean.py`'s three existing
invalid-output assertions had their expected error-message substring
widened from "invalid or collapsed" to "invalid, collapsed, or
under-filled" to match the new combined message.
