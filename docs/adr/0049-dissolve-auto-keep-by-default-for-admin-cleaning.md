# 0049: dissolve auto-keeps constant columns by default, opinionated toward admin-boundary cleaning

## Status

Superseded by ADR-0050 (its `keep` override was removed; the auto-keep/
auto-drop mechanism this ADR introduced remains current). Supersedes
`docs/adr/0046`, `docs/adr/0048`.

## Context

`docs/adr/0046` and `docs/adr/0048` built `dissolve` as a general-purpose
primitive: drop every non-`group_by` column by default, require the caller
to opt columns back in via `keep` (per-column function) or a bulk mechanism
(`fields`/`fields_pattern`/`fields_agg`/`exclude`, mirroring GDAL's `select
--fields --exclude`). That generality was never exercised in practice: every
real admin-boundary-cleaning example in this project's own tutorial reduces
to the same two moves, "keep the ancestor columns that are safely constant"
and "sum or otherwise combine the handful of per-child attributes that
aren't", and the bulk regex/list machinery only existed to let the caller
describe those moves by column name instead of by their actual behavior.

The `"auto"` aggregate function (`docs/adr/0048`) already computes the
information needed to make that decision without the caller describing it
at all: whether a column is constant within every group. Once that check
exists and is cheap to run for every non-`group_by` column (not just ones
the caller names), requiring the caller to name them anyway is redundant
work with no safety benefit: a column named in `fields_pattern` still had
to pass the same constancy check to be retained.

The project's admin-hierarchy pipelines are also confirmed to include a
global admin4 dataset as an eventual target, meaning the number of groups
in a single dissolve call can reach the low hundreds of thousands. The
`"auto"` check's original implementation pulled one row per group back into
Python to find the worst offending group per column; at that scale, that
result set (not the SQL aggregation itself) would become the bottleneck.

## Decision

Every column not in `group_by` is now resolved automatically, with no
`fields`/`fields_pattern`/`fields_agg`/`exclude` parameters at all: `_02_
dissolve` runs one combined query per `group_by` checking `COUNT(DISTINCT
...)` for every remaining column, collapsed via a second aggregation
(`MAX`/`ARG_MAX`) to one summary row regardless of how many groups exist,
so the query result size scales with the number of columns, not the number
of groups. A column that's constant in every group is kept (`any_value`); a
column that isn't is dropped, logging a warning that names every dropped
column, since dropping it was never an explicit request and a caller
scanning logs should be able to see what didn't survive.

`keep` (`{column: aggregate_function}`) remains as the only override,
covering what automatic resolution structurally cannot: a column that's
supposed to vary and be combined (`population=sum`), or a column the caller
wants forced through a specific non-default function regardless of
constancy (`min`/`max`/`first`). `keep={col: "auto"}` still runs the
constancy check, but raises `ValueError` instead of dropping on a
violation, since naming a column in `keep` is an explicit request that
column survive, not a hint to try. This preserves the raise-on-violation
behavior `docs/adr/0048` established for explicit retention, while
changing the *default* (unnamed) case from raise to drop, since an
unnamed column failing the check isn't a caller mistake, it's the expected
outcome for a finer level's own columns.

## Consequences

`dissolve`'s configuration surface shrinks from `group_by`/`keep`/
`fields`/`fields_pattern`/`fields_agg`/`exclude`/`allow_null_group` to
`group_by`/`keep`/`allow_null_group`. Every tutorial example needs no flag
beyond `--group-by` and, when summing/overriding a specific column,
`--keep`. This is a deliberate narrowing to the admin-boundary-cleaning use
case `dissolve` was built for, not a general-purpose column-selection tool;
a caller who genuinely wants to force-drop a column that happens to be
constant (not needed by any current pipeline) has no flag for it and must
post-process the output instead.

The one-row-per-column summary query (replacing the earlier one-row-per-
group fetch) makes the constancy check's cost proportional to schema width,
not group count, which matters concretely now that a global admin4 dissolve
is a stated target: hundreds of thousands of groups no longer means
hundreds of thousands of rows crossing into Python.
