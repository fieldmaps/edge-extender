# 0046: dissolve drops non-group columns by default, raises on null groups

## Status

Superseded by ADR-0049.

## Context

`hdx-scraper-cod-ab-global` dissolves fine admin layers into coarser ones
(e.g. admin3 into admin2) with two independent hand-rolled implementations
that disagree on what happens to a column outside the group key:
`extended.py::_dissolve_all_levels` groups on the full attribute tuple and
drops every other column; `global_.py::_dissolve_level` groups on a single
coalesced pcode and keeps every other column via `first()` (an arbitrary
per-group pick), plus `max(adm_origin)` for provenance. Neither validates
NULLs in the group key: `global_.py` silently excludes them with
`WHERE group_key IS NOT NULL`; `extended.py` doesn't check at all.

`first()`-by-default is unsafe as a general primitive. A per-child
attribute like `population` needs `sum`, not `first`: picking one child's
count instead of summing every child in the group produces a plausible but
silently wrong total, with nothing downstream to catch it. Some columns
(e.g. an ancestor `adm{N}_name` paired with its own `adm{N}_pcode` group
key) genuinely are constant within a group and safe to aggregate
arbitrarily, but the tool has no way to tell those two cases apart from the
column's name alone without hardcoding an admin-hierarchy naming convention
that `topo-tools` otherwise avoids (`schema-propose`'s target schema is
itself a user-supplied YAML, not a fixed convention).

## Decision

`dissolve`'s `_02_dissolve` stage drops every column not in `group_by`
unless the caller explicitly retains it: either individually via `keep` (a
`{column: aggregate_function}` mapping) or in bulk via `fields`/
`fields_pattern` (see `docs/adr/0048` for that mechanism's own design). The
allowed aggregate functions are an explicit allow-list (`first`, `min`,
`max`, `any_value`, `sum`, `auto`), rejecting anything else with
`ValueError` rather than passing an arbitrary function name through to SQL.
A `keep` key that's also a `group_by` column raises `ValueError` (clearly a
caller mistake); a `fields_pattern` match against a `group_by`/`keep`/
`fid`/`geom` column is silently excluded instead, since the pattern wasn't
written with that specific column in mind and excluding it doesn't lose any
explicitly-requested behavior.

Rows with a NULL value in any `group_by` column raise `ValueError` by
default, naming the offending row count, consistent with `topo-tools`'
fail-loud pattern elsewhere (e.g. `clip` aborting on a bad `parent_fid`). An
explicit `allow_null_group=True` switches to dropping those rows instead,
logging the count as a warning.

## Consequences

Retaining any column beyond the group key costs the caller one extra
`--keep`/`--fields`/`--fields-pattern` flag, but every retained column's
aggregation behavior is then visible at the call site instead of being an
implicit, unauditable default. `dissolve` never needs to know about
`adm{N}_*` or any other naming convention: `fields_pattern` gets a pipeline
that has already normalized its columns (e.g. via `schema-apply`) a
one-flag convenience without coupling `core.dissolve` to that convention.
The tradeoff is that a caller who forgets `keep`/`fields`/`fields_pattern`
gets a much narrower output than either prior hand-rolled implementation
defaulted to; this is intentional, since a silently-narrow output is a
`--keep` flag away from being fixed, while a silently-wrong picked value is
not obviously wrong at all.

A bulk mechanism (`fields`/`fields_pattern`) still reintroduces a narrower
version of the same risk: confirmed against a real Senegal admin3 layer
(`tmp/clipped/sen_admin3.parquet`), dissolving into admin2 with
`--fields-pattern 'adm[0-9]+_name.*'` matched not only the intended
`adm2_name`/`adm1_name`/`adm0_name` but also the finer `adm3_name`, which is
not constant within a group (admin2 unit `SN0101` alone absorbs 4
differently-named admin3 units), and the then-default `first()` silently
picked one of them. `docs/adr/0048` covers how `fields_agg="auto"` now
closes this gap by verifying constancy instead of relying on the caller to
scope the pattern correctly.
