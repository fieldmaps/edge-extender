# 0014: Inline ST_XMin/XMax/YMin/YMax in a JOIN ON clause recomputes per pair, not per row

## Status

Accepted

## Context

A third scale bug in `_build_overlaps`'s lineage (see
`docs/adr/0011-overlap-detection-scale-bugs.md` for the first two: wrong
predicate, wide-vs-narrow table). Found when `clean --step issues` hung
indefinitely (57+ min, killed) on real Colombia admin3 data (`col/latest/adm3`,
31,880 fids).

Root cause: `_build_overlaps`'s self-join called `ST_XMax(b.geom)` /
`ST_XMin(a.geom)` / etc. directly inside the JOIN's `ON` clause. DuckDB
recomputes the envelope on every pairwise comparison instead of once per row
, invisible at typical vertex counts, catastrophic here because a few
polygons in this table (the Amazon-region *resguardos indígenas*, large
sparsely-populated admin3 units) have 20k-54k vertices.

Empirical isolation, on the real file:

- Inline `ST_X*/ST_Y*` calls, bbox-only self-join (no geometry predicate at
  all): did not finish in 2+ minutes.
- Same bbox-only join, `xmin/xmax/ymin/ymax` precomputed as columns first:
  3.2s.
- Full predicate (adds `ST_Overlaps`/`ST_Contains`) on the precomputed
  version, in isolation: 6.8s, finds 30 real overlap pairs.
- Same fix inside the actual pipeline (file-backed connection, `--debug`
  profiling overhead, prior-stage memory pressure): 79.8s for the join,
  ~5m22s for the whole `clean` run end to end, both now finite. The 10x
  gap vs. the isolated benchmark is real-world overhead (on-disk DB + WAL,
  debug instrumentation, no thread pinning), not a partial fix.

Four call sites shared the identical inline-recompute anti-pattern (grep
across `topo_tools/core/`): `clean/_02_issues.py` (`_build_overlaps`, the
confirmed/reproduced hang), `extend/_02_lines.py` (neighbor-union self-join),
`change/_02_overlap.py` (crumbs join), `match/_02_assign.py` (pairs join).
One site, `extend/_05_merge.py`, already avoided this by precomputing bbox
columns in its `_05_tmp1`/`v` CTEs, the reference pattern for the fix.

**`SPATIAL_JOIN` considered and ruled out** as an alternative to manual
bbox-prefiltering entirely (the manual prefiltering exists partly to dodge
`SPATIAL_JOIN`'s known ~1x-RAM reservation bug on DuckDB 1.5.2, per
`docs/explanation/topology.md`, added without rigorous benchmarking at the
time). Confirmed via `EXPLAIN` + timing on the real Colombia file:
`SPATIAL_JOIN` only activates when a spatial predicate is the *entire* `ON`
clause, no fid ordering, no `WHERE`, no `UNION`, nothing else. The
detection logic needs `ST_Overlaps(a,b) OR ST_Contains(a,b) OR
ST_Contains(b,a)` plus dedup/self-exclusion, which always breaks the
`SPATIAL_JOIN` rewrite back to a full nested-loop join. Even standalone, a
bare `ST_Overlaps` `SPATIAL_JOIN` took 34s and bare `ST_Contains` took
16-17s, both slower than the 6.8s the fix already achieves for the full
combined predicate with dedup. Separately, the 1.5.2 reservation bug itself
appears fixed in the installed 1.5.5 (a forced-`SPATIAL_JOIN` bare-predicate
query completed fine under a 512MB `memory_limit`), but that's orthogonal to
this fix.

## Decision

Never call `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` inline inside a JOIN's
`ON` clause. Always precompute the four bbox values as real columns on the
table/CTE being joined, at table-creation time, and reference the columns in
`ON` instead. Applied at all 4 sites above: each gained 4 columns on an
existing tmp/narrow table, no new intermediate table introduced. Sites using
`UNNEST(ST_Dump(geom)).geom AS part_geom` needed a wrapping CTE (unnest
first, extract bbox from the materialized `part_geom` in an outer `SELECT`)
, mirroring `_05_merge.py`'s existing `_05_tmp1` shape.

## Consequences

Any future join against a geometry column in this codebase must follow the
same precompute-then-reference pattern. No new unit-test coverage added:
like ADR-0011's second bug, this is vertex-count/scale-dependent, not
correctness-dependent, so the 12-polygon synthetic fixture in
`tests/test_clean.py` cannot manifest it; verification relies on this ADR
plus at-scale profiling against the real Colombia admin3 dataset (see
`docs/explanation/clean.md`'s profiling table). Fix is columns-only (4 extra
scalar columns on an existing tmp table), keeping memory overhead compatible
with DuckDB-WASM in-browser and 2-4GB container deployment targets, no new
whole-table materialization.

`change/_02_overlap.py`'s fix is unverified at matching real-world scale:
Colombia's portolan catalog only has `original.parquet` at adm3 in `latest`
(`v01` has no adm3), so there's no old/new pair carrying the same
pathological polygons to exercise it end to end. Covered by
`tests/test_change.py` for correctness only.
