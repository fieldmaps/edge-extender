# 0050: dissolve drops `keep`, scoped strictly to boundary topology

## Status

Accepted. Supersedes `docs/adr/0049` (retains its auto-keep/auto-drop
mechanism; removes the `keep` override it introduced alongside it).

## Context

`docs/adr/0049` made every non-`group_by` column resolve automatically
(kept if constant per group, dropped with a warning if not), but kept
`keep` around as an escape hatch for two cases: forcing a specific
aggregate function regardless of constancy (`min`/`max`/`first`), and
summing a per-child attribute that's expected to vary (`population=sum`).

That escape hatch is itself outside `dissolve`'s actual purpose.
`topo-tools`' tools exist to fix and maintain boundary *topology*: gaps,
overlaps, coverage, matching a child layer to a parent. Summing or
otherwise combining a demographic/attribute column across the children a
group absorbs is data enrichment, a different kind of operation with its
own correctness concerns (what to do with a partially-covered child,
whether a sum is even the right combinator) that don't belong in a tool
whose only other job is geometry.

## Decision

`keep` is removed entirely, along with `_ALLOWED_AGG_FUNCTIONS`/
`_validate_agg_functions` and the `auto`-vs-explicit distinction it
required. Every non-`group_by` column is now unconditionally: kept via
`any_value` if constant within every group, dropped (with a warning naming
every dropped column) if not. There is no way to force a column through, or
choose a different aggregate function, from `dissolve` itself.

The constancy check (`_distinct_counts`) simplifies alongside this: it no
longer needs to find an *example* offending group for an error message
(there's no `keep={col: "auto"}` raise path left to report one for), just a
max-distinct-count per column, so the query drops the `ARG_MAX`/group-key
machinery `docs/adr/0049` introduced.

## Consequences

`dissolve`'s full configuration surface is now `group_by` +
`allow_null_group` (plus the standard `threads`/`tmp_dir`/`overwrite`/
`debug`/`step` shared across every tool). A pipeline that needs a
summed/combined attribute alongside the dissolved geometry runs that
aggregation as a separate step against the same input, joined back on the
`group_by` columns, rather than through `dissolve`. This is a narrower tool
than either `docs/adr/0046` or `docs/adr/0049` designed, by choice: every
capability removed here was general-purpose column-selection machinery
that no admin-boundary-cleaning use case in this project actually needed.
