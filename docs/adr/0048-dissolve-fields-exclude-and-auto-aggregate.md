# 0048: dissolve's bulk column selection follows GDAL's `select --fields --exclude` shape, defaults to auto-verified aggregation

## Status

Superseded by ADR-0049.

## Context

`docs/adr/0046` established `dissolve`'s drop-by-default behavior: every
column outside `group_by` is dropped unless the caller opts it back in via
`keep` (per-column function) or a bulk mechanism covering many columns at
once. Many COD-AB pipelines dissolving admin3 into admin2 want the opposite
framing: keep the entire schema, dropping only the handful of columns
specific to the level being collapsed away (e.g. `adm3_pcode`,
`adm3_name`).

Naming precedent was checked across CLIs and libraries the project's users
already know before committing to flag names: GeoPandas' `dissolve(by=,
aggfunc=)` has no include/exclude concept at all (it aggregates every
column); QGIS' `native:dissolve`, ArcGIS' `management.Dissolve`, and
Mapshaper's `-dissolve` likewise have no bulk pattern-based selection.
GDAL's modern `gdal vector` CLI does: `gdal vector select --fields <FIELDS>
[--exclude]` selects a field list and a boolean flag inverts it into a drop
list, and separately, `gdal vector combine --group-by <FIELDS>
--add-extra-fields no|sometimes-identical|always-identical` groups by
attribute columns and offers an auto-detecting safety mechanism for
retaining other fields: `always-identical` only keeps a field if it
verified every row in the group actually shares one value, refusing to
guess.

## Decision

`dissolve`'s bulk column selection mirrors GDAL's `select` shape rather than
inventing new vocabulary: `fields` (a list of column names) and
`fields_pattern` (a regex) name the same selection two ways, sharing one
`fields_agg` aggregate function; `exclude` (a boolean) flips whether that
selection is what's *kept* (default) or *dropped* (`exclude=True`, keeping
everything else instead). `group_by` itself is renamed from `by` to match
GDAL's `combine --group-by`, since `by` alone read as ambiguous once paired
with `fields`/`fields_pattern`.

`fields_agg` (and any `keep` function) also gains a new allowed value,
`"auto"`, adopted directly from GDAL's `--add-extra-fields
always-identical` idea, and made the *default* rather than opt-in: before
running the union query, `dissolve` runs one combined `COUNT(DISTINCT ...)`
query per `group_by` across every column resolved to `"auto"`, and raises
`ValueError` naming the column and an example offending group if any group
has more than one distinct non-NULL value. A column that passes is
aggregated as `any_value`. This directly closes the real failure mode
`docs/adr/0046` documents (a `fields_pattern`/`keep_pattern` scoped too
broadly, silently picking an arbitrary value from a non-constant column):
raising catches it before export instead of relying on the caller to have
scoped the pattern correctly. Callers who deliberately want an arbitrary
pick, or `sum`/`min`/`max`, still get it by naming the function explicitly.

`group_by`/`keep` columns are always retained regardless of `fields`/
`fields_pattern`/`exclude`, no error, since there's no genuine contradiction
to catch: `keep` naming a column's own aggregate function is strictly more
specific information than a bulk selection, so it wins without the caller
needing to say so.

## Consequences

One bulk mechanism (list or regex, toggled by a boolean) replaces the two
parallel keep/exclude mechanisms considered earlier in this project's
history, at the cost of the caller writing a negative-lookahead regex or an
explicit `exclude=True` when they want the "keep everything except" framing
that a separate `exclude`/`exclude_pattern` pair would have given directly.
This was accepted because it mirrors a CLI shape (`gdal vector select
--fields --exclude`) the project's target users already know, rather than
maintaining project-specific vocabulary for the same idea.

`"auto"` as the default aggregate function adds one extra query per
dissolve call (a `COUNT(DISTINCT ...)` per group across every auto-resolved
column), traded for turning a silent wrong-value bug into a loud
pre-export failure. A caller who explicitly opts out via `first`, `min`,
`max`, `any_value`, or `sum` skips that check entirely for that column and
is back to the original risk `docs/adr/0046` describes, now deliberately
rather than by default.
