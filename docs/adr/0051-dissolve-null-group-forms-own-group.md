# 0051: dissolve lets a NULL group_by value form its own group, matching GDAL

## Status

Accepted. Supersedes the null-handling portion of `docs/adr/0046` (raise by
default, `allow_null_group=True` to drop instead).

## Context

`docs/adr/0046` made a NULL value in a `group_by` column raise `ValueError`
by default, with `allow_null_group=True` as an opt-in that dropped those
rows from the dissolve instead. Neither branch actually let a NULL-keyed
row survive as its own group; the flag only chose between failing loudly or
excluding the row.

Checked against GDAL empirically (its docs don't state this explicitly):
`gdal vector combine --group-by` treats NULL as its own single group, no
error, no flag, no fields removed, standard SQL `GROUP BY` semantics. This
matters for the real use case `allow_null_group` was built for: a global
composite where some countries don't reach a given admin level, so their
finer-level pcode is NULL. Dropping those rows removes that country's
boundary entirely from the coarser output. Letting the NULL form its own
group (as long as the *other* `group_by` columns still disambiguate it from
every other country, e.g. `adm1_pcode`/`adm0_pcode` alongside a NULL
`adm2_pcode`) keeps the country's boundary in the output instead, tagged
with a NULL pcode reflecting the real absence of that level, which is a
strictly better outcome than losing it.

The remaining risk this raise-by-default guarded against, an upstream bug
that nulls out an entire `group_by` column, produces one giant merged group
covering the whole dataset under the new behavior instead of a hard error.
This was judged an acceptable trade: a dissolve collapsing to one feature
where hundreds were expected is an immediately obvious, visible failure
(wrong row count, one enormous polygon), not a subtle one, so the fail-loud
guard wasn't preventing a genuinely dangerous silent failure, just trading
one obvious failure mode for a different obvious one, at the cost of
breaking the one real use case.

## Decision

`allow_null_group` is removed. `_02_dissolve` runs a single unconditional
`GROUP BY` over `group_by`, with no NULL check, no filtering, and no raise:
a NULL value in a `group_by` column is grouped exactly like any other value,
via DuckDB's native `GROUP BY` semantics, matching `gdal vector combine
--group-by`'s behavior.

## Consequences

`dissolve`'s configuration surface shrinks further, to just `group_by`
(plus the standard `threads`/`tmp_dir`/`overwrite`/`debug`/`step` shared
across every tool). The tutorial's "countries missing an admin level"
example no longer needs a flag at all: grouping by the full ancestor chain
already produces the right result for a country lacking a finer level, a
group of its own instead of a dropped boundary. A caller who genuinely
wants to exclude NULL-keyed rows can filter them out of the input before
calling `dissolve`, the same way GDAL expects a caller to pre-filter if
that's what they want.
