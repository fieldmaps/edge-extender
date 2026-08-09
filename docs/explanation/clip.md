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

1. **`_01_inputs`**: loads the children and parent/clip layers raw via
   `core.io.read_and_reproject`.
2. **`_02_assign`**: tags the children with a constant `source_file` (a
   standalone `clip()` call is always one input file, so `assign-one`'s
   per-file majority vote degenerates to "the whole file shares one
   parent"), calls `core.assign._02_one.main()` directly, then joins the
   resulting crosswalk onto the children to build `{name}_02_clip_in`.
3. **`_03_clip`**: the actual clip logic; see below.
4. **`_04_outputs`**: exports the clipped layer, raising `RuntimeError`
   first if the result is empty (this is also what surfaces the case where
   `assign-one` couldn't match any child to any parent at all). No
   coverage hard gate here.

`mosaic` and `match` both bypass `_01_inputs`/`_02_assign`/`_04_outputs`
and call `core.clip._03_clip.main()` directly on their own already-loaded,
already-assigned tables (via `core.clip.main`, the package's re-exported
name), the same pattern `core.match`/`core.change` use to call
`core.extend`'s stage functions directly. `mosaic` calls it once per run
(its own per-parent-fid loop is `core.clip`'s only subprocess generation);
`match` calls it once too, but batched over its already-reassembled,
already-extended `{name}_03a` table, the second of `match`'s own two
subprocess generations, see
`docs/adr/0020-match-clip-two-subprocess-generations.md`.

## One parent fid at a time, each in its own subprocess

`_03_clip.main()` requires the children table to already carry
`parent_fid` (assign's own output contract) rather than taking a separate
assign table and joining internally, since a caller assembling children
from multiple sources (e.g. match's reassembled per-group output) may not
have one single assign table to join against. Standalone `clip` always
satisfies this itself via `_02_assign`'s join, before `_03_clip` ever runs.

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
