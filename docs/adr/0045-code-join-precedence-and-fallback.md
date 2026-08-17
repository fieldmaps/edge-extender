# 0045: Code join wins on disagreement, falls back on no match

## Status

Accepted.

## Context

`match`, `mosaic`, and standalone `clip` all delegate parent assignment to
`core/assign`'s spatial-overlap logic (`assign_many`/`assign_one`). Some
parent/child layer pairs already carry a matching administrative-code column
(e.g. a pcode), a signal cheaper and usually more reliable than spatial
overlap, but one that can be wrong exactly when a real boundary adjustment
(split/merge/renumbering) or a data error has occurred on one side. Neither
signal alone is safe to trust unconditionally: spatial overlap alone repeats
the failure modes `docs/adr/0019` already documents, and a code join alone
would silently misroute a child whose code is stale or wrong.

## Decision

`core/assign` accepts optional `parent_match_column`/`child_match_column`
kwargs (`assign_many` and `assign_one` both). When given, both signals are
always computed: the existing spatial-overlap result, and an exact code
join, restricted to `(child, parent)` pairs that actually overlap (a code
match against a non-overlapping parent is treated the same as no match at
all). The code result wins whenever one exists, even when it disagrees with
the spatial result, since the code is usually more authoritative than
overlap area for exactly the boundary-adjustment cases this feature targets.
A disagreement is not silently accepted, though: it is recorded on the
output as `assignment_method='code'`, `spatial_agrees=False`, so callers can
surface it as a reviewable issue (`kind='code-mismatch'`) rather than losing
the discrepancy. A child (or, for `assign_one`, a whole file) whose code has
no overlapping-parent match at all falls back to the spatial result, tagged
`assignment_method='spatial_fallback'` (`kind='code-fallback'` downstream).

Omitting both kwargs keeps `_02_assign`'s schema and values exactly as
before (`child_fid`, `parent_fid` only), no behavior change for existing
callers.

## Consequences

`match`, `mosaic`, and standalone `clip` all gained this automatically,
since assignment is a shared leaf primitive rather than duplicated per tool;
`clip` gained an issues report as a result, its first (see
`docs/reference/shared.md`, `docs/reference/clip.md`). The design
deliberately excludes any autodetection of which columns to join on (unlike
`core/change`'s regex-based column matcher): the caller must name both
columns explicitly, which also keeps `core/assign` free of any dependency on
`core/change`, preserving its leaf status under the `core-assign-is-leaf`
import-linter contract.
