# 0023: Standalone clip's multi-file mode processes one children file at a time

## Status

Superseded by ADR-0080 (this pattern moved to `edge-mosaic`, see
ADR-0079; standalone `edge-clip` reverted to a strict 1:1 primitive).

## Context

ADR-0022 gave standalone `clip`'s multi-file mode one shared parent load by
reusing `mosaic`'s existing pattern verbatim: union every children file into
one combined table, run one `assign-one` pass over everyone at once, one
clip pass, then split the result back apart by `source_file` only at
export. Running this against the full portolan catalog (111 countries'
lowest-admin-level layers, clipped against a ~730MB world adm0 file) with
`--debug` showed the parent load itself is fixed (one load, ~25s, +1.4GB
DuckDB memory, shared across every country as intended), but the `assign`
step pushed process RSS to ~7.6GB and was still climbing when the run was
stopped. `core.assign._02_one.py`'s bbox-prefiltered join loops over every
"heavy" (high-vertex) parent part and, each time, joins against *every*
combined children file's parts, not just the ones spatially relevant to
that part's own country. With a world adm0 parent, most countries are
heavy, so the join scales roughly as (heavy parent parts) x (every
country's children combined), not the much smaller (heavy parent parts
near this one country) x (this country's own children) that per-country
processing actually needs.

CLAUDE.md's stated deployment targets are memory-limited containers
(2-4GB RAM, no swap) and DuckDB-WASM's JS-heap-only browser environment.
ADR-0022's combined-table design only fit this specific batch because the
development machine has enough RAM to mask the problem; it would not fit
the stated targets at this scale.

## Decision

Standalone `clip`'s multi-file path now processes one children file at a
time, sharing only the parent load across the whole run:

- `core/assign/_01_inputs.py` is split into `load_children()` and
  `load_parent()`, with `main()` unchanged (calls both, in order) so
  `mosaic` and single-file `clip` keep their existing combined-table
  behavior byte-for-byte. `core/assign/_02_one.py` needs no changes at
  all, since scoping its children table down to one file per call is what
  makes each call's join cheap; the join logic itself is unaware of how
  many files are behind it.
- `api/clip.py` gains a private loop, `_clip_each_file()`, used only when
  `children_paths` is a list. It loads the parent once into a pristine
  `{name}_parent_full` table, then per children file: copies a fresh
  mutable `{name}_parent_01` from it (cheap in-connection table copy, no
  re-read/reprojection), loads just that one file's children, runs assign
  and clip unchanged, and stages the result.
- Staged-then-renamed writes preserve ADR-0022's all-or-nothing guarantee
  without holding every file's clipped result in memory at once: each
  file's export goes to a hidden `.tmp_{name}` file next to its real
  destination (same directory, same filesystem, atomic `Path.replace()`),
  promoted to the final name only once every file in the batch has
  succeeded. Any single empty file is recorded and the loop continues
  (so the eventual error names every failing file, not just the first),
  but nothing is promoted or left behind if any file failed.
- `step` MUST be `None` whenever `children_paths` is a list (`ValueError`
  otherwise): the per-file loop no longer maps onto four independently
  resumable named stages the way the single-file path does. Single-file
  `clip` keeps full `step` support unchanged.
- Under `--debug`, per-iteration table drops are skipped, so only the
  **last** processed file's intermediate tables remain inspectable
  afterward, not all of them; there is no per-file debug Parquet export
  for the multi-file loop (`_STEP_TABLES`/`maybe_export_debug_tables`
  don't apply here, since there's no discrete named-step structure to key
  off in a per-file loop).

`core/clip/_01_clip.py` and `_engine.main()` (the per-`parent_fid`
subprocess mechanism) are reused completely unchanged; both already
operate purely on whatever currently occupies `{name}_child_01`/
`{name}_02_assign`, agnostic to how many files that came from.
`core/clip/_02_outputs.py`'s existing dict-based `main()` is unchanged too,
still used only by the single-file path.

## Consequences

Multi-file `clip` runs now hold roughly (parent + one children file) in
memory at any point, not (parent + every children file), at the cost of
losing per-step resumability for that path and of re-copying the parent
table once per children file (cheap relative to the original file
load/reprojection, but not free, and worth watching at very large file
counts). `--debug` on a multi-file run is for spot-checking one file's
behavior, not full-batch forensics; a caller who needs to inspect every
file's intermediate state must still run single-file `clip` once per file.
ADR-0022's external contract (equal-length `output_paths`, explicit `name`,
one output per children file, hard-fail-before-writing-anything) is
unchanged; only the internal mechanism achieving it is superseded.
