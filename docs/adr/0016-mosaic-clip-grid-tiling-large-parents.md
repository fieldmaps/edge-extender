# 0016: Grid-subdivide the parent boundary before clipping, not count-based batching

## Status

Accepted

## Context

After ADR-0015's per-parent subprocess isolation, the Africa continent-scale
run still OOM'd on a single parent: South Africa, with 4,392 admin4 children
(already Voronoi-extended, so heavily overshot) assigned against a
281,369-vertex parent boundary, by far both the highest child count (next
highest, Tunisia, had 2,084) and the most complex parent geometry (next
highest, Mozambique, 162,667 vertices) in the 47-country set. One subprocess
running `ST_Intersection` for all 4,392 children against that one boundary
in a single query needed more native memory than fits on a 16GB machine,
fully isolated, with the cross-parent leak from ADR-0015 already ruled out.

A sibling project on the same DuckDB-spatial/GEOS stack,
`fieldmaps/admin-boundaries` (`app/_03_build/_03b_clip.py`), solves the
identical class of problem (clipping large numbers of source polygons
against a country boundary) by shrinking what a single `ST_Intersection`
call has to handle, not by limiting row count: the parent boundary is
grid-subdivided into small lossless tiles (`CLIP_CELL`-degree cells, built
strip-by-strip so even subdivision stays memory-bounded), each source
polygon is joined only to the tiles its bbox overlaps (scalar
`ST_XMax`/`ST_XMin`/`ST_YMax`/`ST_YMin` comparisons, explicitly not
`ST_Intersects`, which DuckDB plans as a `SPATIAL_JOIN` reserving roughly
its own RAM), intersected per tile, and unioned back per source row.

Two approaches were built and measured head-to-head against South Africa's
exact failure case (extracted from a surviving diagnostic DuckDB file: 4,392
real children, the real 281k-vertex parent):

| | Count-based batching (500/subprocess) | Grid-tiling (`CLIP_CELL=1.0`) |
| --- | --- | --- |
| Result | Succeeded, 9/9 batches | Succeeded, 4392/4392 children |
| Total time | 119.2s | 7.8s |
| Peak RSS | 4.7 GB | 760 MB |

Grid-tiling won on both axes (15x faster, ~6x less peak memory) and was
verified to produce geometrically identical output: 10 sampled children's
tiled-vs-direct `ST_Intersection` area matched to within ~1e-16 (float
noise). Count-based batching only reduces how much work happens per
subprocess; it still hands GEOS the full 281k-vertex parent on every single
call, so it doesn't address the real driver (parent geometry complexity) and
would still fail on a country with even one child but a sufficiently complex
boundary.

## Decision

`core/clip.py`'s per-parent subprocess worker (`_clip_one_worker`) grid-
subdivides that parent's boundary into `CLIP_CELL`-degree tiles
(`_subdivide_boundary`, `topo_tools/core/constants.py:CLIP_CELL = 1.0`)
before intersecting, joining children to overlapping tiles via bbox
comparison rather than `ST_Intersects`, then reassembling per child with
`ST_Union_Agg` + `ST_CollectionExtract(..., 3)` (polygon parts only). This
runs inside the same per-parent subprocess from ADR-0015, not as an
additional subprocess layer — the two fixes address different problems
(cross-parent leak vs. single-parent cost) and compose without conflict.

## Consequences

`ST_Multi(...)::GEOMETRY` strips any explicit CRS tag DuckDB attached during
computation; re-wrapped with `ST_SetCRS(..., 'EPSG:4326')` so a Parquet
round-trip doesn't produce a CRS mismatch against the `table_out` schema on
`INSERT ... BY NAME` (portolan's own extended.parquet files are CRS-untagged
so this never surfaced against real data, but `tests/test_mosaic.py`'s
synthetic fixtures are explicitly EPSG:4326-tagged and caught it immediately
on the full test run). Full continent-scale run (47 parents including South
Africa) completed end to end with zero memory errors after this fix; the
only remaining failure was `check_gaps` correctly flagging real coverage
holes at the locations of 9 African countries entirely absent from the
local portolan catalog (Botswana, Lesotho, Rwanda, Djibouti, Gabon,
Madagascar, Mauritius, Seychelles, Tanzania) — a test-data completeness
limit, not a code defect.
