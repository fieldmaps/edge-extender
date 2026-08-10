# 0039: has_gaps/check_valid_topology default flips to tolerant, param renamed to gap_maximum_width

## Status

Accepted.

## Context

`has_gaps()`/`check_gaps()`/`has_valid_topology()`/`check_valid_topology()`
(`core/coverage.py`) defaulted their width parameter to `None`, meaning
"any interior hole of any size counts," the zero-tolerance check `extend`
needs since it has no parent/clip layer. Every other caller, `match`,
`mosaic`, `clean` (ADR-0037), and now `stitch` (ADR-0038), passes an
explicit `SNAP_TOLERANCE` override, since each can have a real, legitimate
wide gap in its output (a parent/clip layer's own hole, a gap left
unfilled by design, a real unbatched absence) that a zero-tolerance check
would wrongly reject.

`extend` is the outlier by tool count (1 of 5) and by domain reality:
almost every other layer this pipeline works with has legitimate holes
somewhere in it. Defaulting to the behavior only one caller wants, while
the other four repeat the same override, doesn't match which behavior is
actually the common case.

`0` was considered and rejected as a literal replacement for the current
`None`-triggered code path if reused inside the existing scoped SQL
comparison (`WHERE (ST_MaximumInscribedCircle(h.geom)).radius * 2 <=
gap_maximum_width`): a real hole's inscribed-circle radius is essentially
never exactly zero, so `<= 0` would almost never match anything, silently
disabling the check. The fix is to keep `0` as its own explicit branch
inside `has_gaps()`, reusing the existing cheap interior-ring-count query
(today's `None` branch) rather than routing it through the width-scoped
query, so the two code paths and their relative cost are unchanged, only
which value selects which one.

Separately, the parameter itself was named `max_width` (`has_gaps`/
`check_gaps`) or `max_gap_width` (`has_valid_topology`/
`check_valid_topology`), while `coverage_clean()` in the same file already
named the equivalent value `gap_maximum_width`, GEOS's own `CoverageCleaner`
member name (verified against upstream source in ADR-0002). Standardizing
on that name closes both the intra-file inconsistency and a naming
mismatch with the upstream library.

## Decision

`has_gaps()`, `check_gaps()`, `has_valid_topology()`, and
`check_valid_topology()` now take `gap_maximum_width: float =
SNAP_TOLERANCE`, replacing the old `max_width`/`max_gap_width: float |
None = None` parameter, both the default and the name. `gap_maximum_width
= 0` (not `None`, no longer an accepted value) is the new strict
sentinel, mapped inside `has_gaps()` to the same cheap
interior-ring-count query `None` used to select; any positive value
routes through the existing `gap_geometries_sql`-based width comparison,
unchanged.

`extend/_01_inputs.py` and `extend/_06_outputs.py` are updated to pass
`gap_maximum_width=0` explicitly, the only two call sites that need the
strict behavior. `match/_05_outputs.py`, `mosaic/_03_outputs.py`, and
`stitch/_03_outputs.py` drop their now-redundant explicit
`max_gap_width=SNAP_TOLERANCE` argument, relying on the new default.
`clean/_03_clean.py`'s gap check is unaffected in behavior, only its
keyword name changed to match: it already passes an explicit
`gap_maximum_width_deg` (never relied on `has_gaps`'s default).

## Consequences

A future caller of `check_valid_topology()` that omits `gap_maximum_width`
now gets the tolerant, `SNAP_TOLERANCE`-bounded check by default, matching
what 4 of 5 current tools want, rather than `extend`'s zero-tolerance
check. That inverts which failure mode a careless omission produces:
previously a forgotten override was too strict (crashes loudly on a real,
legitimate gap); now it would be too lenient (a real defect logged as a
warning instead of raised). `extend`'s two call sites carry the explicit
`gap_maximum_width=0` marker precisely so this doesn't happen silently
there. Existing tests asserting the old strict default
(`tests/test_coverage.py::test_has_gaps_tolerates_wide_hole_when_scoped`,
`tests/test_extend.py::test_inputs_closes_noise_scale_gap`) are updated to
pass `gap_maximum_width=0` explicitly, preserving what they actually test.
