# 0082: `assign_one` forces the whole file onto its winner; clip-time drops get their own issue kind

## Status

Accepted.

## Context

`assign_one`'s final join (`core/assign/_one.py`) required `pr.shared_area
> 0` per child, so even a file with a clear majority-vote winner still
dropped any individual child with zero raw overlap with that winner (e.g.
a tiny offshore island digitized slightly outside its parent). For
`edge-mosaic`/standalone `edge-clip`, assignment runs immediately before
clipping, so this only ever produced a hard drop. For `edge-match`,
assignment runs *before* per-group Voronoi extension, so a child dropped
here never got the chance extension gives every other child to be pulled
into coverage.

Separately, `edge-match` defaulted to `assign_many` (per-child plurality),
splitting one input file into as many groups as it has locally-dominant
parents. The actual need across both tools is the opposite bias: force a
file's children together onto its one clear winner by default, and only
split into independent per-child groups for the specific case of a single
poorly-digitized layer whose children genuinely belong to many different
parents (e.g. admin4 fitting into many admin3 units).

## Decision

- `core/assign/_one.py`: drop the `pr.shared_area > 0` requirement from
  the final `_02_assign` join, both the plain and code-join paths. Every
  child in a `source_file` with a determined majority-vote winner is now
  assigned to that winner unconditionally. `{name}_02_unassigned` now only
  holds children from a `source_file` with **no winner at all** (zero
  overlap with every parent, file-wide), not individual stragglers within
  an otherwise-matched file.
- `assign_one` becomes the default for both `edge-mosaic` and
  `edge-match`. `api/edge_match.py::match()` gains `multi_parent: bool =
  False` (CLI: `--multi-parent`); `True` calls `assign_many` instead,
  restoring today's per-child plurality for the many-admin4-into-many-
  admin3 use case.
- A forced-in child that genuinely doesn't overlap its file's winner still
  produces an empty `ST_Intersection` at clip time. `core/edge_clip/
  _engine.py`'s `_clip_one_worker` now writes two outputs per parent-fid
  subprocess instead of one: `output.parquet` (non-empty results, via a
  `LEFT JOIN` against the parent's boundary tiles so a child whose bbox
  misses every tile still emits a row instead of vanishing) and
  `dropped.parquet` (empty-or-null-geometry rows, keeping each child's
  **original**, pre-intersection geometry so a reviewer can see where the
  dropped unit actually is). `main()` accumulates every subprocess's
  `dropped.parquet` into `"{table_out}_dropped"`, tagged with the literal
  `parent_fid` from that loop iteration, mirroring
  `core/edge_match/_02_groups.py`'s `_append_to_reassembly()` pattern.
  Never raises; this is expected/non-fatal (e.g. admin0 vs. a highly
  detailed admin4 is a normal mismatch), so it must be visible, not fatal.
- Every caller adds a `kind='clip-empty'` issue row sourced from its own
  `*_dropped` table: `unit_a` = child fid, `parent_fid` populated,
  `reason` describing the empty intersection.
  (`core/edge_mosaic/_03_outputs.py`, `core/edge_match/_05_outputs.py`,
  `core/edge_clip/_02_outputs.py`.) Standalone `edge-clip` gains a general
  issues file for the first time: previously it only existed when
  `code_join` was set; `api/edge_clip.py::clip()` now always resolves an
  `issues_path` default and always checks/writes it, since `clip-empty`
  rows can occur regardless of `code_join`.

## Consequences

A non-overlapping child's drop point moves from assign time ("didn't
overlap its file's winner") to clip time ("empty intersection with its
assigned parent"), for every one of `edge-mosaic`/`edge-clip`/`edge-
match`'s default paths. The final output set of surviving children is
unchanged from before this decision for `edge-mosaic`/`edge-clip` (same
children were already being dropped, just silently); for `edge-match`,
some previously-dropped children may now survive, since forcing them into
their file's group gives Voronoi extension a chance to physically reach
the winning parent before clipping runs.

`edge-match`'s own ADR-0081 sentinel-orphan-group passthrough mechanism
depends on `_02_unassigned` containing individual stragglers to have any
per-child orphans to rescue. Under the new default, `_02_unassigned` only
ever contains file-wide-unassigned children, so ADR-0081's mechanism is
only exercised per-child when `--multi-parent` is also set; it still
functions identically to before under that combination.

References ADR-0019 (the majority-vote-by-count mechanism itself is
unchanged, only what happens to a non-overlapping child within the
winning file changes) and ADR-0081 (whose per-child orphan rescue now
requires `--multi-parent` to see individual, rather than only whole-file,
orphans).
