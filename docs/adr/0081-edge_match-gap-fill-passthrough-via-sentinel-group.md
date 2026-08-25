# 0081: `edge-match` gap-fill passthrough via a sentinel-parent-fid orphan group

## Status

Accepted.

## Context

`edge-mosaic` gained an opt-in gap-fill passthrough (ADR-0078, folded into
`--merge` by ADR-0079): a whole child file with no overlapping parent is
kept unclipped in the output instead of dropped. `edge-match` has the same
"drop a zero-overlap child" behavior (`core.assign.assign_many()`'s
`_02_unassigned`), and the same case for wanting to keep it: a genuinely
missing/mismatched parent boundary shouldn't silently lose real child
geometry from the output.

But `edge-match` uses `assign-many`, a per-child (not per-file) assignment
strategy, so a raw port of `edge-mosaic`'s per-file passthrough doesn't fit:
there is no "whole file" concept to keep or drop, only individual children.
A naive "keep the dropped child's raw geometry" port would also ship
un-extended geometry with no Voronoi gap-fill at all, unlike every other
child in the output, which is always extended before being clipped.

## Decision

Reuse `edge-match`'s own per-group extension pipeline for zero-overlap
children instead of inventing a new code path: extension only needs a
group's own children, never a parent, so a group made of nothing but
zero-overlap orphans can be extended exactly like every other group, it
just never gets clipped afterward (there is no parent to clip against).

- `core/edge_match/_constants.py`: new `PASSTHROUGH_PARENT_FID = -1`,
  guaranteed absent from real parent fids (always >= 0).
- `core/edge_match/_02_groups.py`: `main()` gains a `passthrough: bool`
  param. After the normal per-parent-group loop, when `passthrough` is
  true and `{name}_02_unassigned` is non-empty, one more group runs through
  the identical `_group_worker` subprocess, sourcing its children from
  `{name}_02_unassigned` (the full child rows, not just `child_fid`/`geom`)
  and tagged with `PASSTHROUGH_PARENT_FID` instead of a real parent fid.
  Run *after* every real group, not before: `_append_to_reassembly()`'s
  first call fixes `{name}_03a}`'s schema via `CREATE TABLE`, and the
  orphan group carries no merge columns (there's no parent to join them
  from); appending it last means its `INSERT ... BY NAME` just leaves those
  columns NULL, whereas appending it first would create a schema without
  them and break the first real group's own `INSERT ... BY NAME` (extra,
  unmatched columns). The shared per-group body was extracted into
  `_run_group()` so both the real-group loop and the one-off orphan call
  use identical export/spawn/record-or-append logic.
- `core/edge_match/_03_clip.py`: `main()` gains a `passthrough: bool` param.
  When true, sentinel-tagged rows are split out of `{name}_03a}` into a
  `{name}_03a_real}` table before `clip_main` runs on the real-parent-only
  remainder, then unioned straight into `{name}_04}` afterward
  (`UNION ALL BY NAME`, unclipped, the same idiom `edge-mosaic`'s own
  passthrough uses), before `_04_stitch` gets a chance to resolve seams
  against the orphan's clipped neighbors.
- `core/edge_match/_05_outputs.py`'s `_build_issues()`: gains a
  `passthrough: bool` param. When true, the `unassigned` issues part is
  omitted entirely (every `_02_unassigned` child is now covered by either a
  `dropped_group` row, if its orphan-group extension failed, or a new
  `passthrough` row, if it succeeded), and a `passthrough` part is added,
  mirroring `core/edge_mosaic/_03_outputs.py`'s own `_build_issues()`
  pattern.
- `api/edge_match.py::match()`: same `merge_columns: list[str] | bool =
  False` signature and `_resolve_merge_columns()` helper as `mosaic()`
  (ADR-0079), resolved lazily once per run (on first need, across
  `--step` boundaries, the same lazy-resolution pattern `edge-mosaic`'s
  single-file path uses); `passthrough = bool(merge_columns)` threaded into
  `groups.main()`, `clip.main()`, and `outputs.main()`.

## Consequences

**Materially weaker safety profile than `edge-mosaic`'s passthrough**, and
this is documented plainly rather than presenting the two as equivalent
(`docs/explanation/edge_match.md`, `docs/reference/shared.md`).
`edge-mosaic`'s passthrough geometry was already a finished, validated
`edge_extend()` output before the run started. `edge-match`'s orphan group
is extended fresh, alone, with zero neighboring-parent context of any kind,
and its own per-group extension has no majority/plurality vote to fall back
on if the extension misbehaves, since there was nothing to vote on (unlike
a normal multi-child group, where other children can outvote one bad one).

`edge-match`'s `--carry-column`/`carry_columns` no longer exists, replaced
by `--merge`/`merge_columns`, a breaking CLI/API rename matching
`edge-mosaic`'s own ADR-0079 rename: any caller using `--carry-column` must
switch to `--merge`. `core.assign`/`core.edge_clip` are untouched; the
"which children get kept unclipped" decision lives entirely in
`core.edge_match`'s own stages, the same precedent ADR-0078 set for
`edge-mosaic`'s passthrough.

References ADR-0078 (edge-mosaic's passthrough, the precedent for keeping
this decision out of `core.assign`/`core.edge_clip`) and ADR-0079
(`--merge`'s boolean-or-value semantics, reused here unchanged).
