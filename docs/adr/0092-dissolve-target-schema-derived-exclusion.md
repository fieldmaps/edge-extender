# 0092: `dissolve` gains `exclude`/`target_schema`-derived column exclusion

## Status

Accepted

## Context

`dissolve`'s auto-keep logic retains any column that's constant per group,
including one that's merely all-NULL. Dissolving COD-AB admin boundaries
adm3→adm2 kept `adm3_name1`/`adm3_name2` (all-NULL alt-language columns) in
the adm2 output, and adm1/adm0 too, since they stayed constant (NULL) all
the way down. The workaround was a manual `SELECT * EXCLUDE (...)` after
every call (issue #14).

An all-NULL column carries no data signal, so nothing content-driven,
including `schema-map`'s real cardinality/containment inference, can tell
which level it belongs to. The only mechanism that can is name-pattern
matching against a `TargetSchema` (`adm{n}_...`), which already existed as
a private helper inside `schema-fill`: `core/schema_fill/_levels.py`'s
`field_prefix`/`level_prefix`/`detect_levels`, and `_02_fill.py`'s private
`_column_families()` (the same regex already generalizes past `{n}_pcode`/
`{n}_name` to any same-prefix suffix, including alt-language variants like
`adm3_name1`/`adm3_name2`, see `docs/adr/0075`).

A plain `exclude: list[str]` kwarg alone would fix the one-off case, but
the issue's real recurring workflow is dissolving one finest file to every
coarser level (adm3→adm2→adm1→adm0). Each call needs a different,
growing exclude list by hand; missing one column at a deeper level quietly
reintroduces the same bug. Reusing schema-fill's level-detection lets
`dissolve` derive the right exclude set from `group_by` itself, once per
call, with no manual list to maintain.

## Decision

Promote `field_prefix`, `level_prefix`, `detect_levels`, and the renamed
`column_families()` (was `_02_fill.py`'s private `_column_families()`)
into a new shared module, `core/schema_map/_levels.py`. `schema-fill`
imports them from there instead of defining them locally, no behavior
change to `schema-fill` itself.

`dissolve()` gains two independent, optional kwargs:

- `exclude: list[str] | None`: exact column names, dropped unconditionally
  before the constancy check, unknown names ignored.
- `target_schema: str | Path | None`: a target-schema YAML path. When
  given, `dissolve` detects `group_by`'s own deepest matching level (the
  deepest `n` where `code_field.format(n=n)` or `name_field.format(n=n)`
  is in `group_by`) and unconditionally excludes every column at a finer
  level, raising `ValueError` if no `group_by` column matches any
  detected level.

A new, narrowly-scoped import-linter contract permits this:
`core.dissolve` MAY import `core.schema_map`, `core.schema_map` MUST NOT
import `core.dissolve`. This narrows, rather than reverses, CLAUDE.md's
"`core.dissolve` is a neutral leaf, none of the ten may import back"
statement: `dissolve` stays independent of every actual tool package
(`edge_extend`, `edge_match`, `topo_clean`, `change`, `edge_mosaic`,
`schema_fill`, `schema_refactor`, `schema_crosswalk`), gaining only a
dependency on `schema_map`'s generic, data-free `TargetSchema`/
level-detection utility, not `schema_map`'s own cardinality-based
inference engine.

## Consequences

`exclude` remains available with no schema dependency for ad hoc or
non-hierarchy data. `target_schema` is opt-in: a caller reusing one
hierarchy-derived schema across a multi-level dissolve run gets the
correct exclusion recomputed automatically at every level, instead of
maintaining a hand-written, easy-to-under-maintain list per call. A file
whose `group_by` doesn't match any detected level gets `ValueError`
rather than a silent no-op, so a caller who supplies `target_schema` but
picks the wrong schema or grouping notices immediately.
