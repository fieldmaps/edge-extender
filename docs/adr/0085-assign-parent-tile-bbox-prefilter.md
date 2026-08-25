# 0085: `prepare_parent_tiles()` bbox-prefilters against the children's combined extent

## Status

Accepted.

## Context

Real-data testing of `edge-mosaic`/`edge-match`'s multi-file mode with
three bordering countries against the full global admin0 file
(`fieldmaps/adm0-generator`'s `adm0_polygons.parquet`, ~730 MB, 195+
countries) showed both tools spending several minutes and multiple GB of
RSS tiling the *entire* parent file before either ever touches the three
countries that actually matter. `prepare_parent_tiles()`
(`core/assign/_one.py`) dumped every part of the whole `{name}_parent_01`
table and grid-tiled every part at or above `CLIP_TILE_MIN_VERTICES`,
unconditionally, with zero awareness of which children exist. A parent
part whose bbox doesn't overlap any child's bbox can never produce a real
pair in `_build_pairs()`'s downstream join, since real overlap always
implies bbox overlap.

**Rejected: an exact spatial-overlap check between bbox and tiling.** Would
mean running `ST_Intersects` against the very heavy, untiled parent
polygons that tiling exists to make cheap to query in the first place, a
circular cost. `docs/explanation/performance.md`'s RTREE experiment found
explicit spatial indexes give zero/negative benefit in this engine for
adjacent-geometry joins, and that DuckDB's own `SPATIAL_JOIN` rewrite
already handles bbox rejection cheaply for a plain `ST_Intersects`
predicate. A bbox-only filter can only over-include, never wrongly exclude
a real overlap, and the exact overlap decision still happens correctly
downstream once tiling is scoped down.

**Rejected: a new lightweight raw/uncleaned bbox-read helper for
children.** DuckDB spatial exposes no zero-scan/metadata-only bbox for
GeoParquet/GPKG/Shapefile/GeoJSON reads. Skipping `ST_MakeValid`/cleaning
for a cheaper scan risks a marginally different (possibly smaller) extent,
a real correctness risk for a small perf gain, so the pre-scan reuses the
existing, already-tested `load_children()`/`load_and_clean_child()`
loaders instead.

## Decision

`prepare_parent_tiles()` gains an optional `child_bbox: tuple[float,
float, float, float] | None` parameter (`xmin, ymin, xmax, ymax`); when
given, `_02_parent_parts` is filtered down to only parts whose bbox
intersects it, before either the heavy/light split or the tiling loop.
A new helper, `child_bbox_extent(conn, name)`, returns the combined bbox
of every row in `{name}_child_01`, or `None` if empty.

`_build_pairs()`'s own call (`use_cached_tiles=False`, the single-file
path) always passes `child_bbox=child_bbox_extent(conn, name)`: the child
is already loaded at that call site in every caller (`edge-mosaic`,
single-file `edge-match`, standalone `edge-clip`), so this is a zero-added
-cost win. `edge-mosaic`'s and `edge-match`'s multi-file loops each add a
pre-scan pass before their own `prepare_parent_tiles()` call: load each
children file in turn (`load_children`/`load_and_clean_child`), read its
bbox, fold it into a running combined bbox, drop the child table, and move
on, then tile the parent once against the combined extent.

`--merge` gap-fill is unaffected: it reads from `{name}_parent_01`/
`{name}_parent_full`, the full untouched parent snapshot, never from the
filtered `_02_parent_parts`/`_02_parent_tiles` scratch tables.

## Consequences

Tiling a large shared parent against a handful of children files no
longer wastes time/memory on parts nothing will ever be assigned to.
The multi-file pre-scan reads and cleans each children file twice (once
for the bbox scan, once in the real per-file loop), an acceptable cost
since children are the small side of this workload by construction.
