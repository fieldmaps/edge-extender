# Clip Explanation

`edge-clip` is the standalone extraction of the clipping step `edge-match` and
`edge-mosaic` each ran internally before this extraction: assign every child to
its parent, then intersect it against that parent's geometry, dropping
anything that clips to empty. Unlike `edge-match`/`edge-mosaic`'s internal use of the
same clipping mechanism, standalone `edge-clip` never expects a caller to have
already assigned `parent_fid` itself; it does that internally, always via
`assign-one` (see `docs/explanation/assign.md`, `docs/adr/0021`). It has no
opinion about whether its output is coverage-clean; that's `edge-stitch`'s job
downstream.

## Pipeline

`api.edge_clip.clip()` is a strict one-children-file/one-parent-file/one-output
primitive (see `docs/adr/0080`), running four named stages once, in order
(`step` MAY select just one for standalone debugging):

1. **`inputs`**: `topo_tools.core.assign.load_children()`/`load_parent()`,
   called directly (no local wrapper file, the same pattern `edge-mosaic`
   already uses), loads the one children file (tagged with its own full
   path as `source_file`) and the parent/clip layer.
2. **`assign`**: `topo_tools.core.assign.assign_one()`, also called
   directly; see `docs/explanation/assign.md`, `docs/adr/0021`.
3. **`_01_clip`** (clip's own local stage): joins `{name}_02_assign`'s
   `parent_fid` onto `{name}_child_01` to build `{name}_02_clip_in`, then
   calls `_engine.main()` (the actual clip logic; see below).
4. **`_02_outputs`** (clip's own local stage): exports `{name}_03`
   directly, raising `RuntimeError` first if the result is empty.

`edge-mosaic` and `edge-match` both bypass all four of these steps and call
`core.edge_clip._engine.main()` directly on their own already-loaded,
already-assigned tables (via `core.edge_clip.main`, the package's re-exported
name), the same pattern `core.edge_match`/`core.change` use to call
`core.edge_extend`'s stage functions directly. `edge-mosaic` calls it once per run
(its own per-parent-fid loop is `core.edge_clip`'s only subprocess generation);
`edge-match` calls it once too, but batched over its already-reassembled,
already-extended `{name}_03a` table, the second of `edge-match`'s own two
subprocess generations, see
`docs/adr/0020-match-clip-two-subprocess-generations.md`.

## One parent fid at a time, each in its own subprocess

`_engine.main()` requires the children table to already carry `parent_fid`
(assign's own output contract) rather than taking a separate assign table
and joining internally, since a caller assembling children from multiple
sources (e.g. match's reassembled per-group output) may not have one
single assign table to join against. Standalone `edge-clip` always satisfies
this itself via `_01_clip`'s join, before `_engine.main()` ever runs.

For each distinct `parent_fid`, present children and that one parent's
geometry are exported to per-fid Parquet files and handed to a freshly
spawned OS subprocess (`multiprocessing.get_context("spawn")`), which loads
them into its own DuckDB connection and intersects. A single query
intersecting every assigned child against every parent's full geometry at
once, and later a per-parent loop within one process, both OOM'd at
continent scale: repeated `ST_Intersection` calls leak GEOS's native heap
the same way `edge_extend()`'s Voronoi machinery does, and only a fresh process
per parent reliably reclaims it. See `docs/adr/0015` for the isolation
decision itself.

A caller driving `edge-clip`/`edge-mosaic`/`edge-match` programmatically (not via the CLI)
MUST run its own entry point from a real `.py` file, not stdin or `-c`:
`spawn` re-execs workers by re-importing `__main__` from that file's path,
so a worker started from stdin fails immediately with a `FileNotFoundError`
that surfaces as a generic "worker exited with no result" error, easy to
mistake for OOM.

Within one parent's subprocess, that parent's boundary is grid-tiled
before intersecting once its vertex count reaches `CLIP_TILE_MIN_VERTICES`
(`core.edge_clip.subdivide_boundary`, `_tiling.py`), joining children to tiles
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

If a parent fid's subprocess fails (crash, OOM, missing output), `edge-clip`
raises `RuntimeError` immediately and aborts the whole run, rather than
skipping just that parent fid and continuing. This is the one canonical
clip failure behavior; there is no configurable "continue past a bad
group" mode.
