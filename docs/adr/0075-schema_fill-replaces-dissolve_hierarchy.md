# 0075: `schema-fill` replaces the composite `dissolve-hierarchy` design

## Status

Accepted.

## Context

`fieldmaps/admin-boundaries`'s `app/_03_build/_03b_clip.py` hand-rolls
`_leaf_attr_select()`, a `COALESCE`-based fill-down over every admin level
in a leaf table, purely so the same leaf table can be dissolved to every
coarser level afterward. It carries no signal distinguishing a genuine
leaf-depth row from a coarser row whose deeper columns were only ever
filled down; a caller inspecting the leaf table alone cannot tell the two
cases apart.

An initial `topo-tools` design (`dissolve-hierarchy`) treated this as a
single composite tool: fill down, then dissolve every level 1..N in one
call, first with a hardcoded P-code-shaped column convention, then
generalized to reuse `schema-map`'s `TargetSchema` mechanism. That design
was rejected once the real target became clear: "prepare is where we
should have been targeting all of our work. If we just had a properly
attributed dataset to begin with we could just dissolve it normally."
Once a leaf table is properly attributed (every row's real depth known),
plain `dissolve` (unmodified) already builds any single level correctly;
no composite multi-output, `{n}`-templated tool is needed at all.

## Decision

Split the fill-down concern into its own schema-group primitive,
`schema-fill` (`api.schema_fill.fill()`), living in
`topo_tools/core/schema_fill/`, not `topo_tools/core/dissolve/`: the
operation is a schema/attribute-completeness concern (does every row carry
a full, consistent hierarchy of columns), not a geometry-aggregation
concern, and it reuses `schema-map`'s `TargetSchema` YAML mechanism to
discover the hierarchy generically rather than assuming any column-naming
convention (e.g. P-codes).

`schema-fill` does two things, single input, single output, no `{n}`
template:

1. Cascades every level column family (grouped by shared suffix, e.g.
   every `*_pcode`, every `*_name`) down from its nearest non-NULL
   shallower level via `COALESCE`.
2. Appends a depth column, `adm_lvl` by default (overridable via
   `depth_column`), stamping each row with the deepest level whose
   *original*, pre-fill code column was non-NULL.

A caller then runs plain `dissolve` once per level, unmodified: its
existing auto-keep-constant-column behavior (any column constant within a
group is kept via `any_value`, see `docs/explanation/dissolve.md`) already
carries `adm_lvl` through each dissolve call correctly, since a dissolved
group's `adm_lvl` is constant exactly when every leaf row under it agrees
on how deep the real data went. No change to `dissolve` itself was needed.

Level detection (`detect_levels()`, `core/schema_fill/_levels.py`) finds
every level 1..N via the schema's `code_field` prefix and requires each to
have its own code column, raising `ValueError` naming any gap. This
generalizes to a single detected level (e.g. an admin1-only input) with no
special-casing, verified directly: `levels` is simply `[1]`.

`schema-fill` is meant to run against an already-clipped/stitched layer
(an `edge-match`/`edge-mosaic` output), not a raw pre-clip source, since
level detection needs the target schema's columns already settled by that
point (see `docs/explanation/schema_fill.md`).

## Consequences

The originally-built `dissolve-hierarchy` tool (its own core package, api
module, tests, and docs) was deleted entirely, superseded by this simpler
two-tool composition (`schema-fill` then `dissolve`, called once per
level). `schema-fill` alone cannot materialize a whole new row for a
territory with zero source rows at all, it only completes an existing
row's shallower attributes; there is no mechanism elsewhere in the
pipeline for that gap either.
