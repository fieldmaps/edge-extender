# 0080: `edge-clip` reverts to a strict one-children-file/one-parent-file/one-output primitive

## Status

Accepted. Supersedes `docs/adr/0022`, `docs/adr/0023`, `docs/adr/0024`.

## Context

Standalone `edge-clip` gained a multi-file mode (ADR-0022/0023/0024) to
batch many children files against one shared parent load without reloading
a large global parent (e.g. a ~730MB world adm0 file) per country. But
`edge-mosaic` was already the tool meant to own that exact global-build use
case (already-extended children, `assign-one`, attribute merging); its own
multi-file mode just didn't actually solve the memory problem until it
adopted `edge-clip`'s per-file, cached-parent-tiles pattern (ADR-0079). With
`edge-mosaic` now the proven memory-safe home for batched global builds,
`edge-clip` carrying its own copy of the same machinery is pure duplication:
two independent implementations of the same fold-as-you-go, cached-tile,
fid-offset pattern, doubling the surface a future bug fix or profiling
finding has to be applied to.

## Decision

Strip `edge-clip` back down to a strict one-children-file/one-parent-file/
one-output primitive:

- `topo_tools/api/edge_clip.py`: delete the private multi-file loop
  (`_clip_each_file()`) and the `single_path is None` dispatch branch; delete
  the list-handling branches for `children_paths`/`output_paths`/
  `issues_paths`/`name`. `clip()` now takes one children path, one parent
  path, one output path, and one issues path, no lists anywhere.
- `topo_tools/cli/main.py`'s `edge-clip` command: remove `--input`/
  `--output`/`--issues` (the repeatable/comma-splittable multi-file options)
  and `--name` (no longer needed without a multi-file run to name). The
  positional `INPUT_FILE`/`CLIP_FILE`/`OUTPUT_FILE` arguments and
  `--issues-file` are unaffected.
- `edge-clip`'s own `--carry-column`/`carry_columns` (list-only, no
  merge/passthrough concept) is unaffected by this ADR; `edge-clip` never
  had a gap-fill concept, since a strict 1:1 primitive has no drop/keep
  decision to make.

`core.assign`/`core.edge_clip` themselves (the neutral-leaf modules
`edge-clip`'s per-fid subprocess isolation and `assign-one`'s majority vote
live in) are untouched: `edge-mosaic`'s multi-file mode calls the same
`prepare_parent_tiles()`/`assign_one(use_cached_tiles=True)` primitives
`edge-clip`'s multi-file mode used to, just from `api/edge_mosaic.py`
instead of `api/edge_clip.py`.

## Consequences

`edge-clip`'s CLI/API surface loses multi-file batching entirely, a breaking
change for any caller using `--input`/`--output`/`--issues`/`--name`: that
caller must switch to `edge-mosaic` (already-extended children only; see
`docs/reference/edge_mosaic.md`) or call standalone `edge-clip` once per
children file itself. `edge-clip` returns to being a small, easy-to-reason-
about primitive with one job, matching the shape `edge-stitch`/`topo-detect`
already have. ADR-0022/0023/0024's Context/Decision/Consequences stay as
historical record of the profiling evidence and design that produced the
pattern now living in `edge-mosaic`; only their Status lines change.
