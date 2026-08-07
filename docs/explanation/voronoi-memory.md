# Voronoi resampling distance and memory ceilings

`attempt.py` picks a per-file starting resampling distance rather than
always using a fixed default, and `_03_points.py` caps how many
interpolated points any single real line segment can produce. Together
these avoid a Voronoi-algorithm degeneracy and let files with finer native
detail keep it. See `docs/adr/0012-voronoi-collinearity-degeneracy-fixed.md`
and `docs/adr/0013-memory-gb-budget-removed.md` for why these specific
designs were chosen over the alternatives that were tried first.

## Per-segment interpolation cap

`_03_points.py` decomposes each boundary line into its own real
vertex-to-vertex segments and caps interpolation at
`MAX_POINTS_PER_SEGMENT = 100` points per segment (`_constants.py`),
bounding the largest exactly-collinear point cluster fed to
`ST_VoronoiDiagram` independent of that segment's raw length. Segments
shorter than the cap threshold fall back to the original whole-line
resampling formula, unaffected.

## Per-file starting distance

`attempt.py` computes `effective_distance = MIN(DEFAULT_DISTANCE,
natural_res)`, where `natural_res` is the median real segment length across
the file. This lets files with genuinely finer source detail than
`DEFAULT_DISTANCE` (e.g. Philippines) start at their own native resolution
instead of losing that detail to a coarser default; it can never coarsen
an already-detailed file, since `natural_res` only wins when it's finer.
If the effective distance still fails or produces too many points
(`MAX_POINTS`), `attempt.py` retries by doubling it, up to 10 times.

## Known memory floors with no runtime gate

Two bottlenecks are `DISTANCE`-independent — no resampling lever shrinks
either — and have no runtime memory check:

- `phl_admin3` OOMs in `_01_inputs.py`'s `ST_CoverageClean` pass (triggered
  by invalid-edge detection in the source data) before `lines` or `attempt`
  ever run; needs ~5.9GB.
- `idn_admin3` needs ~5.4GB in `_02_lines.py`'s neighbor-union bbox
  self-join, which uses whole-fid (not per-part) bboxes deliberately — see
  `docs/adr/0001-avoid-global-union-agg-operand.md` for why per-part bboxes
  regress Chile instead.

A future OOM on either file at a given memory ceiling is an expected,
already-diagnosed cost, not a regression — see
`docs/adr/0013-memory-gb-budget-removed.md` for why no runtime budget check
was kept.
