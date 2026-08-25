# 0083: `edge-mosaic`'s `--merge` gap-fill is parent-orphan, not child-orphan

## Status

Accepted. Supersedes ADR-0078 and the passthrough half of ADR-0079.

## Context

ADR-0078/0079's `--merge`/`merge_columns` kept a whole **children file**
with zero spatial overlap with any parent unclipped in the output (a
country genuinely missing a matching entry in the source layer). The
actual requirement is the opposite entity: a **parent** matched by zero
children (a territory with no children data covering it at all) should
carry through using the parent's own geometry and attributes, so the
output stays a complete coverage layer over the parent set. `edge-match`'s
own ADR-0081 sentinel-group mechanism is a distinct, differently-scoped
thing (per-child, not per-file/per-parent) and is untouched by this
decision.

## Decision

Parents with zero matched children are only detectable by diffing the
full, pre-truncation parent set against `{name}_02_assign`'s distinct
`parent_fid`s, since `assign_one` already narrows `{name}_parent_01` down
to only matched fids before `edge-mosaic`'s clip stage runs (ADR-0082).
A full-parent snapshot (`{name}_parent_full`) is taken before `assign_one`
runs, only when `merge_columns` is truthy.

- `core/edge_mosaic/_01_clip.py`: the child-`source_file`-diff passthrough
  block is removed entirely. A new `fill_gaps(conn, name, *,
  carry_columns, result_table, parent_snapshot_table)` builds
  `{name}_02_gap_fill` as every `parent_snapshot_table` row whose `fid` is
  absent from `{name}_02_assign`'s distinct `parent_fid`s, carrying
  `carry_columns` straight off the parent row itself (no join needed,
  since the row already is the parent, so gap-filled rows get real
  attribute values, not NULL), and unions it into `result_table`.
- Single-file path (`api/edge_mosaic.py`): the "inputs" step snapshots
  `{name}_parent_01` into `{name}_parent_full` right after
  `load_parent()`, when `merge_columns` is truthy; the "clip" step calls
  `clip.main(..., raise_if_empty=False)` then, if truthy, `fill_gaps(...)`,
  then a local "raise if nothing survived" check runs *after* gap-fill so
  an all-unassigned-children run that still gap-fills every parent doesn't
  spuriously raise.
- Multi-file path (`_mosaic_multi_file()`): already built exactly this
  snapshot (used to reset `{name}_parent_01` each iteration); `fill_gaps`
  runs **once**, after the per-file loop, against the fully accumulated
  `{name}_02_assign`, not per-iteration.
- `core/edge_mosaic/_03_outputs.py`: the `passthrough: bool` param is
  renamed `fill_gaps: bool`; the `unassigned_where` passthrough-exclusion
  clause is dropped (every `{name}_02_unassigned` row is reported
  unconditionally again); the `kind='passthrough'` issue part (sourced
  from `{name}_02_passthrough`) is replaced with `kind='gap-fill'`
  (sourced from `{name}_02_gap_fill`): `unit_a` NULL, `parent_fid`
  populated, `source_file` NULL, `reason` describing the unmatched parent.

## Consequences

A parent with zero matched children keeps its own geometry/attributes in
the output when `--merge` is set, reported as a `kind='gap-fill'` issue
row. A child (or whole children file) with zero overlap with any parent
is unaffected by `--merge` either way: it stays dropped and reported per
ADR-0082's `unassigned`/`clip-empty` kinds, regardless of the flag.
`edge-clip` and `edge-match` gain no equivalent parent-orphan mechanism;
extending this pattern to either would need its own justification.
