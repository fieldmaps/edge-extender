# 0088: `--merge` split into a boolean plus column filters; mosaic/match gap-fill parity

## Status

Accepted.

## Context

`edge-mosaic`/`edge-match`'s `--merge` flag was a single boolean-or-value
CLI flag (`merge_columns: list[str] | bool` in `api.mosaic()`/`api.match()`),
coupling two behaviors: copying parent columns onto every matched child,
and keeping an unmatched parent (mosaic) or unmatched child file (match)
in the output unclipped instead of dropping it (`docs/adr/0077`,
`docs/adr/0081`, `docs/adr/0083`). There was no way to control which of
the *child's own* columns survived in the merged output, only the
parent's, and a real parent/child column-name collision always raised
`ValueError` with no way to resolve it automatically.

The two tools' passthrough mechanisms also diverged, not just in name:
mosaic's `--merge` kept an unmatched *parent* (zero matched children) via
its own geometry, with no mechanism for an unmatched *child file* (simply
dropped, reported as `kind='unassigned'`). match's `--merge` was the
mirror image: it kept an unmatched *child file* via its own
already-extended geometry, with no parent-side gap-fill at all. This
contradicted the tools' own superset relationship (`edge-mosaic` exists
purely to skip `edge-match`'s redundant extension step, see
`docs/explanation/edge_mosaic.md`): running `edge-match` on a raw child
set and `edge-mosaic` on the already-extended version of that same set,
against the same parent, produced different `--merge` results depending
on which unmatched-entity shape the input happened to hit.

## Decision

- `--merge` becomes a pure boolean flag (`is_flag=True`), controlling only
  passthrough/gap-fill and turning column merging on generally. Bare
  `--merge` keeps the historical default: every parent column is copied
  onto matched children.
- Four new flags narrow that default, each a comma-separated column list:
  `--parent-include`/`--parent-exclude` (which parent columns get copied
  onto matched children) and `--child-include`/`--child-exclude` (which
  of the child's own columns survive in the output). Each pair is
  mutually exclusive with itself; a parent-side flag MAY combine with a
  child-side flag. All four require `--merge`.
- A fifth flag, `--prefer [parent|child]`, resolves a real parent/child
  column-name collision automatically instead of raising: `parent` keeps
  the parent's column, `child` keeps the child's. Omitting `--prefer`
  preserves the historical raise-on-collision default. `--prefer`
  requires `--merge` and is mutually exclusive with all four narrowing
  flags (it resolves a collision across the default, unnarrowed column
  sets; combining it with manual narrowing adds interaction cases not
  worth the complexity).
- Both tools gain both passthrough mechanisms. Parent gap-fill is shared
  verbatim via a new `core.assign.fill_unmatched_parents()` helper
  (relocated from mosaic's own `fill_gaps()`), since the logic is
  identical for both tools. Child-file passthrough is reimplemented
  per-tool, since the underlying pipelines genuinely differ: mosaic's
  version is a direct SQL union (its children are already extended);
  match's version runs the orphan child file through a full per-group
  Voronoi-extension subprocess (its children are raw). mosaic gained a
  new `kind='passthrough'` issues row (superseding `kind='unassigned'`
  when `--merge` is set); match gained a new `kind='gap-fill'` row.
- Column resolution is shared via `core.assign.resolve_column_selection()`/
  `resolve_merge_columns()`/`validate_merge_flags()` (`core/assign/_column_selection.py`),
  called identically from both tools' api layers, replacing what had been
  byte-identical duplicated private functions in each.

## Consequences

Any existing `--merge iso_3,adm0_name` invocation breaks; it becomes
`--merge --parent-include iso_3,adm0_name`. Omitting `--prefer` preserves
today's raise-on-collision default, so no silent behavior change for a
caller that never hit a collision. `edge-mosaic` now reports a
`kind='passthrough'` issues row it never did before, when a whole child
file has zero overlap with any parent; `edge-match` now reports a
`kind='gap-fill'` row it never did before, when a parent has zero matched
children. `edge-mosaic` run on an already-extended child set and
`edge-match` run on the raw version of that same set, against the same
parent and assign strategy, now produce identical `--merge` results
(same carried/passed-through rows, differing only in the pre-existing,
unrelated fact that a normally-clipped row's `parent_fid` is always
`NULL` on both tools' output, since the shared `core/edge_clip/_engine.py`
excludes it there regardless of `--merge`). Supersedes
`docs/adr/0077`/`docs/adr/0081`/`docs/adr/0083`'s divergent per-tool
passthrough scoping.
