# Clip Explanation

`clip` is the standalone extraction of the clipping step `match` and
`mosaic` each ran internally before this extraction: assign every child to
its parent, then intersect it against that parent's geometry, dropping
anything that clips to empty. Unlike `match`/`mosaic`'s internal use of the
same clipping mechanism, standalone `clip` never expects a caller to have
already assigned `parent_fid` itself; it does that internally, always via
`assign-one` (see `docs/explanation/assign.md`, `docs/adr/0021`). It has no
opinion about whether its output is coverage-clean; that's `stitch`'s job
downstream.

## Pipeline

1. **`inputs`**: `topo_tools.core.assign._01_inputs.main()`, called
   directly from `api.clip.clip()` (no local wrapper file, the same
   pattern `mosaic` already uses) loads and unions any number of children
   files, each tagged with its own full path as `source_file`, and loads
   the parent/clip layer exactly once regardless of how many children
   files were given.
2. **`assign`**: `topo_tools.core.assign._02_one.main()`, also called
   directly. Its majority vote is `PARTITION BY source_file`, so combining
   many children files into one table still computes each file's own
   independent majority-vote parent, not one vote across everything; see
   `docs/explanation/assign.md`, `docs/adr/0021`.
3. **`_01_clip`** (clip's own local stage): joins `{name}_02_assign`'s
   `parent_fid` onto `{name}_child_01` to build `{name}_02_clip_in`, then
   calls `_engine.main()` (the actual clip logic; see below).
4. **`_02_outputs`** (clip's own local stage): with a single children
   file, exports `{name}_03` directly, raising `RuntimeError` first if the
   result is empty. With multiple children files, first checks every
   children file's `source_file` still has at least one surviving row in
   `{name}_03`, raising `RuntimeError` naming any that don't **before**
   writing anything, then exports each children file's own subset (via a
   `source_file`-filtered temp view) to its own paired destination. No
   coverage hard gate here either way.

`mosaic` and `match` both bypass all four of these steps and call
`core.clip._engine.main()` directly on their own already-loaded,
already-assigned tables (via `core.clip.main`, the package's re-exported
name), the same pattern `core.match`/`core.change` use to call
`core.extend`'s stage functions directly. `mosaic` calls it once per run
(its own per-parent-fid loop is `core.clip`'s only subprocess generation);
`match` calls it once too, but batched over its already-reassembled,
already-extended `{name}_03a` table, the second of `match`'s own two
subprocess generations, see
`docs/adr/0020-match-clip-two-subprocess-generations.md`.

## Multiple children files, one parent load

Reloading and reprojecting a large parent/clip layer (e.g. a global admin0
file, hundreds of MB) for every children file dominates runtime when
clipping many children files against the same parent one call at a time.
Since `core.assign`'s `_01_inputs`/`_02_one` were already built to combine
many children files behind one parent load for `mosaic`'s own multi-file
case, and their per-`source_file` grouping already keeps each file's
assignment independent, `clip` reuses them unchanged rather than growing
its own separate multi-file mechanism. The only new work is in
`_02_outputs`, splitting the combined result back apart by `source_file`
into the caller's own paired output files, since (unlike `mosaic`) `clip`'s
multi-file case still needs one output per children file, not one combined
output. See `docs/adr/0022`.

## One parent fid at a time, each in its own subprocess

`_engine.main()` requires the children table to already carry `parent_fid`
(assign's own output contract) rather than taking a separate assign table
and joining internally, since a caller assembling children from multiple
sources (e.g. match's reassembled per-group output) may not have one
single assign table to join against. Standalone `clip` always satisfies
this itself via `_01_clip`'s join, before `_engine.main()` ever runs.

For each distinct `parent_fid`, present children and that one parent's
geometry are exported to per-fid Parquet files and handed to a freshly
spawned OS subprocess (`multiprocessing.get_context("spawn")`), which loads
them into its own DuckDB connection and intersects. A single query
intersecting every assigned child against every parent's full geometry at
once, and later a per-parent loop within one process, both OOM'd at
continent scale: repeated `ST_Intersection` calls leak GEOS's native heap
the same way `extend()`'s Voronoi machinery does, and only a fresh process
per parent reliably reclaims it. See `docs/adr/0015` for the isolation
decision itself.

A caller driving `clip`/`mosaic`/`match` programmatically (not via the CLI)
MUST run its own entry point from a real `.py` file, not stdin or `-c`:
`spawn` re-execs workers by re-importing `__main__` from that file's path,
so a worker started from stdin fails immediately with a `FileNotFoundError`
that surfaces as a generic "worker exited with no result" error, easy to
mistake for OOM.

Within one parent's subprocess, that parent's boundary is grid-tiled
before intersecting once its vertex count reaches `CLIP_TILE_MIN_VERTICES`
(`core.clip.subdivide_boundary`, `_tiling.py`), joining children to tiles
via bbox comparison rather than one `ST_Intersection` against a
possibly-million-vertex whole. Below the threshold, the parent is clipped
directly with no subdivision. Tile size is solved from that parent's own
vertex density (`_adaptive_cell_size`) rather than a fixed constant,
calibrated so South Africa's worst real case (281k vertices) lands at
~1 degree cells; sparser or simpler parents get coarser cells automatically.
See `docs/adr/0016` (grid-tiling a large parent's boundary before
intersecting) and `docs/adr/0017` (the adaptive threshold/cell size) for
the full empirical detail.

## Hard-fail on the first bad parent fid

If a parent fid's subprocess fails (crash, OOM, missing output), `clip`
raises `RuntimeError` immediately and aborts the whole run, rather than
skipping just that parent fid and continuing. This is the one canonical
clip failure behavior; there is no configurable "continue past a bad
group" mode.
