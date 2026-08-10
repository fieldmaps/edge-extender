# 0026: assign-one's parent-tile cache insert must be BY NAME

## Status

Accepted.

## Context

ADR-0024 split `core/assign/_02_one.py`'s heavy-parent tiling into
`prepare_parent_tiles()`, which declares `{name}_02_parent_tiles` with an
explicit schema (`parent_fid, geom, xmin, xmax, ymin, ymax`) and then
inserts each heavy part's tiles into it with a positional `INSERT INTO ...
SELECT`. The `SELECT` built its bbox columns from `bbox_columns_sql()`
(`core/duckdb_utils.py`), which emits them in a different order (`xmin,
xmax, ymin, ymax` vs. the table's `xmin, ymin, xmax, ymax`). A positional
insert doesn't check column names, so every heavy tile's `ymin`/`xmax`
values were silently swapped.

This broke the bbox prefilter for every parent part that needed grid
tiling, anywhere in a run, not just one file: most callers still got some
(possibly wrong) match via a lighter-weight fallback path, but Burundi's
only real overlap required its own heavy tile with no fallback, so it got
zero pairs and zero clipped rows. That tripped ADR-0022's all-or-nothing
multi-file guarantee and discarded all 110 otherwise-successful staged
outputs in a 111-country batch run. Found by writing standalone scripts
that called `prepare_parent_tiles()`/`_build_pairs()` directly and
inspecting each stage's table contents until the raw bbox values in
`_02_parent_tiles` showed the swap.

## Decision

Changed the insert to `INSERT INTO "{name}_02_parent_tiles" BY NAME`,
matching the convention `core/clip/_engine.py` already uses
(`INSERT INTO "{table_out}" BY NAME`), so a future reordering of either
side can't silently corrupt data again.

## Consequences

No behavior change for a correctly-ordered insert; a future column-order
mismatch between a manually-declared schema and `bbox_columns_sql()`'s
output now raises instead of silently swapping values. Added
`tests/test_clip.py::test_clip_heavy_parent_tiling_finds_real_overlap`, a
regression test using a synthetic high-vertex circle polygon: none of the
existing 56 tests exercised the >= `CLIP_TILE_MIN_VERTICES` tiling code
path at all, since every prior fixture used tiny polygons.
