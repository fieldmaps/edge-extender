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

With a single children file, `api.clip.clip()` runs four named stages once,
in order (`step` MAY select just one for standalone debugging):

1. **`inputs`**: `topo_tools.core.assign._01_inputs.main()`, called
   directly (no local wrapper file, the same pattern `mosaic` already
   uses), loads the one children file (tagged with its own full path as
   `source_file`) and the parent/clip layer.
2. **`assign`**: `topo_tools.core.assign._02_one.main()`, also called
   directly; see `docs/explanation/assign.md`, `docs/adr/0021`.
3. **`_01_clip`** (clip's own local stage): joins `{name}_02_assign`'s
   `parent_fid` onto `{name}_child_01` to build `{name}_02_clip_in`, then
   calls `_engine.main()` (the actual clip logic; see below).
4. **`_02_outputs`** (clip's own local stage): exports `{name}_03`
   directly, raising `RuntimeError` first if the result is empty.

With multiple children files, `api.clip.clip()` instead runs a private
per-file loop (`_clip_each_file()`); `step` is not usable in this case.
See "Multiple children files, one at a time" below.

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

## Multiple children files, one at a time

Reloading and reprojecting a large parent/clip layer (e.g. a global admin0
file, hundreds of MB) for every children file dominates runtime when
clipping many children files against the same parent one call at a time
(ADR-0022). An initial design shared that load by combining every children
file into one table before a single `assign`/`clip` pass, reusing
`core.assign`'s `_01_inputs`/`_02_one` exactly as `mosaic` does. Profiled
against the full portolan catalog (100+ countries against one world admin0
parent), that combined-table `assign` pass alone pushed process RSS past
7.6GB and climbing: `_02_one`'s bbox-prefiltered join scales with (heavy
parent parts) x (every children file's parts combined), not just the parts
near each individual country.

`_clip_each_file()` (`api.clip.clip()`'s private multi-file loop) instead
loads the parent once into a pristine `{name}_parent_full` table, then for
each children file: makes a fresh mutable copy of it (cheap in-connection
table copy, no re-read/reprojection), loads only that one file's children
via `core.assign._01_inputs.load_children()`, and runs the unchanged
`_02_one`/`_01_clip` stages, so each file's join only ever involves that
file's own children, not every country's combined. Each file's clipped
result is staged to a hidden temp file next to its real destination and
only promoted (`Path.replace()`) once every file in the batch has
succeeded, keeping the same "fully succeed or write nothing" guarantee
ADR-0022 established without holding every file's result in memory at
once. See `docs/adr/0023` for the full profiling evidence and design.

Cutting memory this way exposed a separate cost: `core.assign._02_one.py`'s
`_build_pairs()` grid-tiles every high-vertex parent part before joining
children to it, work that depends only on the parent, never the children.
Run once per file across the full portolan batch, that redundant tiling
pushed wall-clock into multiple hours, against a ~9.5 minute baseline for
the same 111 countries clipped as one combined call. `_clip_each_file()`
now calls `assign_stage.prepare_parent_tiles()` once, before the per-file
loop starts, and every iteration's `assign_stage.main()` call reuses that
cached decomposition (`use_cached_tiles=True`) instead of rebuilding it.
See `docs/adr/0024`.

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
