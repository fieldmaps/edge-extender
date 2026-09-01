# 0096: Voronoi exterior cells clipped to world bounds, conditionally, per cell

## Status

Accepted

## Context

`edge-extend` on real portolan-catalog Chile and Indonesia adm2 produced
output with coordinates outside valid WGS84 range (e.g. `ymin=-99` for
Chile, `xmax=187` for Indonesia), confirmed via `portolan add`'s
`PRTLN-CNV004` CRS-mismatch check refusing to catalog both files. The
affected fids were always the peripheral ones (Isla de Pascua, Antártica
Chilena, Magallanes for Chile; the eastern Papua group for Indonesia).
`_04_voronoi.py`'s `ST_VoronoiDiagram` call builds one diagram from every
boundary point in a file at once; a point on the outer edge of that point
cloud has a mathematically unbounded cell, which GEOS closes using an
auto-sized clipping envelope based on the point cloud's own extent, not any
real-world constraint. Over country-scale lon/lat point clouds, that
auto-envelope overshoots valid WGS84 range for the outermost cells.

Two earlier attempts at a fix were tried and rejected:

- Intersecting the raw diagram against a world-bounds rectangle *before*
  the per-cell `ST_Dump`/`UNNEST` (one `ST_Intersection` call on the whole
  `GEOMETRYCOLLECTION`) OOM'd Chile's run: the temp DuckDB file grew to
  54GB with no output ever written. Same "one giant blob operand" anti-
  pattern `docs/adr/0001` already documents for a different stage; GEOS
  processing one collection with ~100k+ parts as a single intersection
  operand is far more expensive than the equivalent per-row calls.
- Intersecting every dumped cell against the world-bounds rectangle
  unconditionally (cheap, no OOM) broke `edge-match`'s synthetic tests:
  every retry distance failed with a raw GEOS `TopologyException` during
  coverage-clean, even though the test's coordinates (0-12 range) are
  nowhere near ±180/±90. Running a small, well-within-bounds cell through
  `ST_Intersection` against an operand spanning -180..180/-90..90
  perturbs its vertices enough (GEOS's overlay re-nodes the whole polygon
  against both operands' combined precision) to break exact-match shared
  edges with untouched neighbor cells.

## Decision

Clip a cell only when its own bbox already exceeds `-180/-90/180/90`
(`ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` checked per row), leaving every
interior cell byte-identical to its pre-fix geometry. Confirmed against
real Chile/Indonesia adm2 data (clean `edge-extend` run, `portolan add`
accepts both outputs) and the full test suite (`edge-match`'s synthetic
tests pass unchanged).

## Consequences

A peripheral cell that does get clipped can still introduce
`SNAP_TOLERANCE`-scale noise against its interior neighbor's shared edge;
`_05_merge.py`'s existing whole-layer `coverage_clean()` pass already
absorbs this for real-world data, confirmed by both Chile and Indonesia
passing `_06_outputs.py`'s zero-tolerance `check_valid_topology` gate.
