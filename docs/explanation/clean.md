# Cleaning Reference

`clean` detects and fixes coverage defects (gaps, overlaps) in a single
polygon layer using `ST_CoverageClean`. Ported from the sister JS app's
interactive Topology Cleaner tool
(`topo-tools-js/src/lib/tools/topology-cleaner/`); this doc covers what
changed in the port and why, and the `ST_CoverageClean` parameter semantics
the design depends on.

## Usage

```sh
topo-tools clean example.geojson
```

```python
from topo_tools import clean

clean("example.geojson")
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_cleaned` suffix.

| Option | Description |
| --- | --- |
| `--issues-file` | Issues report path. Defaults to `OUTPUT_FILE` with an `_issues` suffix. |
| `--maximum-gap-width` | `auto` (fill only thin/sliver-shaped gaps, default), `all` (fill every detected gap), or a number in decimal degrees. |
| `--snapping-distance` | `auto` (GEOS's computed default, default) or a number in decimal degrees. Noding robustness knob only. |
| `--overwrite` | Overwrite an existing output file. |
| `--threads` | DuckDB thread count. |
| `--debug` | Keep intermediate tables, export to Parquet, log timing/memory per query. |
| `--tmp-dir` | Intermediate DuckDB + Parquet location. |
| `--step` | Run only one named stage: `inputs`, `issues`, `clean`, `outputs`. |

```sh
# Only auto-fill thin/sliver-shaped gaps, leave the rest for review
topo-tools clean example.gpkg --maximum-gap-width auto

# Cap gap-filling at ~0.0001 degrees (~11m at the equator)
topo-tools clean example.parquet --maximum-gap-width 0.0001
```

Run `topo-tools clean --help` for the full, always-current option list.

## Pipeline

1. **`_01_inputs`** -- reads and reprojects to EPSG:4326 via the shared
   `core.io.read_and_reproject()` helper, **without** `extend`'s own auto-clean
   pre-check. This is deliberate: `clean`'s whole purpose is to detect
   defects in the *raw* input, so the detection stage needs to see them, not
   a table `ST_CoverageClean` has already silently rewritten.
2. **`_02_issues`** -- detects gap/overlap regions, writing one issues table
   (`{name}_02`). Gap detection always runs; overlap detection is skipped
   (written empty directly) whenever `has_coverage_violations()` is already
   False -- see "Skipping overlap detection when the coverage is already
   valid" below.
3. **`_03_clean`** -- fixes gaps/overlaps via a single `ST_CoverageClean`
   call (gated: a no-op copy only if the input has no coverage violations
   *and* no detected gap qualifies to fill under the resolved
   `gap_maximum_width` -- see "`has_coverage_violations()` alone cannot
   stand in for gap detection" below; that check is only about
   overlaps/mismatched edges, so a gap-only input still needs
   `ST_CoverageClean` to actually run), validated against invalid edges, a
   total-area floor, and a per-fid collapse/geometry-type check, raising
   immediately if any fails (see "Validating a coverage-clean result"
   below).
4. **`_04_outputs`** -- validates overlaps are gone (hard gate), logs
   (never raises on) any gaps still unfilled by design, and exports both the
   cleaned dataset and the issues report.

## Skipping overlap detection when the coverage is already valid

`main()` checks `has_coverage_violations()` (`ST_CoverageInvalidEdges_Agg`,
the shared `core/coverage.py`) before running `_build_overlaps`
(`_02_issues.py`'s bbox-prefiltered O(n^2) self-join), and writes an empty
overlaps table directly when it's already `False` -- a coverage with no
invalid edges cannot contain an overlapping or nested pair either. Gap
detection (`_build_gaps`) always runs regardless: unlike overlaps, no
cheaper GEOS primitive answers "are there any gaps" without doing the same
whole-table union `_build_gaps` itself needs to extract them. See
`docs/adr/0007-skip-overlap-detection-when-valid.md`.

`has_coverage_violations()` alone cannot stand in for gap detection -- it
only detects overlaps/mismatched edges, never gaps (see
`docs/reference/shared.md`). `_03_clean.py`'s fix-stage gate also checks
whether any detected gap qualifies to fill under the resolved
`gap_maximum_width`, not `has_coverage_violations()` alone (see "Pipeline"
above). See `docs/adr/0008-has-coverage-violations-misses-gaps.md`.

## Sliver detection/fixing was removed

Earlier versions also detected (but never auto-fixed) slivers -- near-miss
boundary mismatches. Dropped entirely: never fixable without re-noding the
whole coverage (an unacceptable side effect for unattended batch use), and
detection itself reproducibly OOM'd on real data even at small scale. Any
near-miss boundary mismatch is now an upstream data-quality issue outside
this tool's scope -- fixing it remains a human decision (re-digitizing,
manual QGIS/ArcGIS editing), just without an automated detector flagging
candidates. See `docs/adr/0006-sliver-detection-removed.md`.

## `ST_CoverageClean` parameter semantics -- verified against upstream source

This mattered enough to check the actual GEOS/duckdb-spatial source rather
than assume JS's UI defaults translate directly (`duckdb-spatial`'s
`src/spatial/modules/geos/geos_module.cpp`/`geos_geometry.hpp`, and GEOS's
own `include/geos/coverage/CoverageCleaner.h`/`src/coverage/CoverageCleaner.cpp`):

- **`snapping_distance`** has a real computed auto-default:
  `extent_diameter / 1e8` (`computeDefaultSnappingDistance`).
  `setSnappingDistance(x)` is a no-op when `x < 0`, so omitting the argument
  (DuckDB's `Bind()` defaults a missing arg to `-1.0`) keeps this
  auto-computed value. `0` explicitly disables snapping; a positive value
  overrides it.
- **`gap_maximum_width` has NO computed auto-default** -- the C++ class
  member is hardcoded to `0.0` ("a width of zero prevents gaps from being
  merged"). `setGapMaximumWidth(x)` is also a no-op when `x < 0`, so an
  omitted argument leaves it at `0.0`, i.e. **no gap-filling at all**. This
  is why `extend`/`match`'s existing `coverage_clean()` calls (which never
  pass a positive `gap_maximum_width`) never fill gaps -- and why JS's "fill
  up to 2x the widest detected gap" was purely a client-side slider-seeding
  heuristic, not anything GEOS computes on its own. It's also why `clean`'s
  own `--maximum-gap-width auto` has to compute a real width itself (see
  below) rather than leaning on any GEOS-side default the way
  `--snapping-distance auto` can.
- **Naming**: `coverage_clean()` (the shared `core/coverage.py`) calls
  `ST_CoverageClean` positionally (`geoms, snapping_distance,
  gap_maximum_width`), passing `-1` for either argument a Python `None`
  omits -- DuckDB binds named arguments to compiled scalar functions by
  position, not name, so a conditional named-arg call is unsafe here (see
  `docs/adr/0003-st-coverageclean-positional-args.md`). The CLI/API layer
  (`--maximum-gap-width`, `--snapping-distance`, and the matching
  `api.clean.clean()` kwargs) follows GDAL's `gdal vector clean-coverage`
  word order for the gap one, since that's what a human actually types;
  `api.clean.clean()` is the one place the two namings meet.
- `ST_CoverageClean`'s gap-merge only fills **fully-enclosed** holes -- a
  ring of polygons surrounding missing area (a lake, a missing admin unit).
  An open "inlet" gap between two side-by-side, non-enclosing polygons is
  left untouched regardless of `gap_maximum_width` (demonstrated with an
  isolated 2-polygon fixture: identical output whether
  `gap_maximum_width` was `-1`, a tiny value, or 1 full degree). GEOS's own
  class doc says as much: "gaps which are not fully enclosed ... are not
  removed." This is also why `_02_issues.py`'s gap-detection query (interior
  rings of the whole-table union) misses open inlets -- they aren't
  fillable "gaps" by this tool's or GEOS's own definition.

## `--maximum-gap-width auto|all|<degrees>`

- `auto` (default when the flag is omitted) -- fills only gaps whose *shape* looks like a digitization sliver,
  regardless of their absolute width. `gap_maximum_width` is a pure width
  cutoff with no shape concept of its own (verified live against GDAL's
  `gdal vector clean-coverage` docs), so this computes the width to feed
  into it: the widest gap's own width *among only the gaps classified as
  thin* (`{name}_02.thinness_ratio <= DEFAULT_THINNESS_RATIO`), directly in
  degree-space from `{name}_02`'s stored gap geometries (`max((
  ST_MaximumInscribedCircle(geom)).radius * 2)`, GEOS's own width metric)
  plus a small epsilon (`AUTO_GAP_WIDTH_EPSILON_FACTOR` in `_constants.py`)
  so the widest thin gap itself clears the `<=` comparison. "Thin" is a
  Polsby-Popper compactness score (`4*pi*Area/Perimeter^2`, 1.0 = circle,
  ->0 = elongated crack) at or below `DEFAULT_THINNESS_RATIO = 0.3`
  (`core/clean/_constants.py`) -- the same formula and cutoff guidance
  ArcGIS Pro's own "Polygon Sliver" data-quality check uses to flag slivers.
  Not user-configurable: a gap's absolute width says nothing about whether
  it's a digitization artifact or a real feature (a small real pond and a
  narrow real strait both exist), but its shape, independent of scale, is
  what the sliver-detection literature already uses to make this call -- if
  a dataset needs different behavior than the fixed cutoff produces, tune
  `--maximum-gap-width <degrees>` directly instead of the thinness cutoff.
  Known, accepted imprecision: since GEOS only ever compares by width, a
  non-thin gap narrower than the widest thin gap would also get swept in.
  When no gap qualifies as thin, the argument is omitted entirely (no
  gap-filling).
- `all` -- fills every gap the detection stage found, using a fixed
  `GAP_MAXIMUM_WIDTH_ALL_DEG = 360` (`_constants.py`), confirmed safe across
  the full `0`-`360°` range once `coverage_clean()`'s named-argument bug was
  fixed (see `docs/adr/0003-st-coverageclean-positional-args.md`).
- A bare number is an explicit cap in decimal degrees, passed straight
  through to `ST_CoverageClean` with no conversion.

## Validating a coverage-clean result

`_03_clean.py`'s `main()` makes a single `ST_CoverageClean` call at the
resolved target width (from `auto`/`all`/an explicit value) and validates
it against **both** `has_coverage_violations()` *and* a total-area sanity
floor -- the invalid-edges check alone passes a totally empty result as
"no violations," confirmed directly, so it can't catch a collapsed output
on its own. `main()` raises immediately if either check fails.

An earlier escalation-ladder retry approach was removed after the two
failure modes it worked around both turned out to be
`coverage_clean()`'s named-argument bug (see "Naming" above), not
independent `ST_CoverageClean` instability. See
`docs/adr/0003-st-coverageclean-positional-args.md`.

### The total-area floor is anchored to detected overlap area, not dataset size

The floor scales with what was actually detected, not a flat fraction of
dataset size (which can't distinguish a large, legitimate overlap-resolution
cost on a small dataset from real corruption -- see
`docs/adr/0009-area-floor-anchored-to-overlap-area.md`):

```
min_area = input_area * (1 - AREA_NOISE_FACTOR) - overlap_area * OVERLAP_LOSS_HEADROOM
```

- `AREA_NOISE_FACTOR = 0.02` bounds baseline loss when **no** overlaps are
  detected -- double the ~1% per-fid renoding drift confirmed on real
  defect-dense data (see "Collapse vs. drift" below), so a
  defect-unrelated fid drifting by its normal amount can't tip a small,
  overlap-free dataset below the floor.
- `overlap_area` is `SUM(ST_Area(geom))` over `{name}_02`'s `kind =
  'overlap'` rows, in the same degree² units as `input_area`/`output_area`.
- `OVERLAP_LOSS_HEADROOM = 3.0` allows resolving an overlap to cost up to
  3x its own detected footprint -- `ST_CoverageClean` can redraw a fid's
  boundary well beyond the immediate overlap it's resolving, confirmed up
  to ~1.5x on a real regression case (see "Defect-adjacent exemption"
  below).

### The total-area floor alone misses a small, localized collapse

The total-area floor only bounds the *summed* output area, so a single
small feature collapsing entirely can hide inside it if the rest of the
dataset is much larger. The result is also checked per fid:

- **Defect-adjacent exemption.** A fid touching a gap that gets filled, or
  party to a detected overlap, is exempt from both checks below, by any
  amount -- `ST_CoverageClean` can redraw that fid's whole neighborhood, not
  just the immediate defect.
- **Collapse vs. drift, for everything else.** A defect-unrelated fid
  collapsing to empty fails this rung outright. A defect-unrelated fid that
  merely shifts area (nonzero, nonempty) only logs a warning --
  `ST_CoverageClean`'s whole-table renoding measurably shifts even fully
  unrelated boundaries on defect-dense real data.
- **Geometry type.** `ST_Area()` sums only the polygonal members of a mixed
  `GEOMETRYCOLLECTION`, so a fid partly reduced to a stray line or point
  during the fix could otherwise still measure as area-preserving. Any fid
  whose fixed geometry isn't a `POLYGON`/`MULTIPOLYGON` fails validation.

Both checks compare against exact, defect-derived bounds rather than a
fraction of the whole dataset -- a percentage floor on a per-fid basis was
tried and rejected, since full containment (one fid entirely absorbed by
another) and gap-neighborhood redistribution are both legitimate
100%-loss outcomes for the fid actually involved.

## `--snapping-distance auto|<degrees>`

`auto` passes `-1` positionally to `ST_CoverageClean`, a no-op that keeps
GEOS's real computed default. An explicit value (decimal degrees, passed
straight through) overrides it. This is a **noding-robustness knob only** -- per
GEOS's own doc comment, "a large snapping distance may introduce
undesirable data alteration."

## Issues file schema

`key VARCHAR, kind VARCHAR, area_m2 DOUBLE, max_width_m DOUBLE,
thinness_ratio DOUBLE, unit_a BIGINT, unit_b BIGINT,
unit_a_area_change_m2 DOUBLE, unit_b_area_change_m2 DOUBLE,
filled_area_m2 DOUBLE, geom GEOMETRY`. `kind` is `'gap'` or `'overlap'`.
`thinness_ratio` and `filled_area_m2` are populated only for gap rows;
`unit_a`/`unit_b` (the two fids involved) and
`unit_a_area_change_m2`/`unit_b_area_change_m2` are populated only for
overlap rows. Geometry is always Polygon, so any of `extend`'s four export
formats (including Shapefile) can hold the issues file.

The `_area_change_m2`/`filled_area_m2` columns are the actual measured
*outcome* of the fix, not the defect as originally detected -- computed by
`_04_outputs.py` from `{name}_01` and `{name}_03` after `_03_clean.py` has
run, since that's the first point both the pre- and post-fix geometry are
available together. For an overlap row, each is that unit's own real area
change (output minus input); for a gap row, `filled_area_m2` is how much
of the gap's own area ended up covered by the cleaned output (`0` if the
gap was left unfilled by design). `_03_clean.py`'s own success log line
reports the same idea at the whole-dataset level (total area
gained/lost, as a percentage) regardless of which individual defects
caused it.

## Units: decimal degrees in, meters out

`--maximum-gap-width` and `--snapping-distance` are decimal degrees, passed
straight through to `ST_CoverageClean` with zero conversion -- the same
units `_01` is already stored in (EPSG:4326), and the same convention
GDAL/OGR uses for any distance parameter on an unprojected layer (native
CRS units, not meters). What you pass is exactly what GEOS receives, with
no dataset-dependent scaling in between -- important when tuning these
values against a specific `ST_CoverageClean` result, since a hidden
conversion factor would mean the number on the CLI and the number GEOS
actually sees are never quite the same thing.

`clean` reports every detected gap and overlap regardless of size -- no
floating-point noise floor is applied, after testing found no native GEOS
jitter to guard against. See
`docs/adr/0010-noise-floor-removed-no-jitter-found.md`.

The *output* side still reports in meters for human readability: the
issues file's `area_m2`/`max_width_m` columns are computed from raw
degree-space geometry via a centroid-latitude `cos_lat_factor`
(`core/clean/_units.py`, one degree of longitude shrinks by
`cos(latitude)`, scaled by the dataset's centroid latitude) -- approximate
over very large north-south extents, but adequate for a reporting column,
not a cleaning tolerance.

## `check_gaps` is deliberately not reused as a hard gate

Unlike `extend`/`match`, `_04_outputs.py` does **not** call `extend`'s
`check_gaps()` on the final output -- `clean` can legitimately leave gaps
unfilled by design (`--maximum-gap-width auto` on a compact/non-thin gap, or
a numeric cap narrower than some detected gap), so raising on any remaining
gap would make the tool crash on
its own default-adjacent behavior. Instead it logs a warning with a count of
how many detected gaps remain uncovered, tested via `ST_Contains` against a
point on each gap's surface -- visibility for the issues file, not a failure
condition. `check_overlaps()` **is** reused as a hard gate here too, but by
the time `_04_outputs.py` runs it, `_03_clean.py`'s own validation (see
above) has already confirmed `{name}_03` has no invalid edges -- or raised
before returning. This check is now a defensive
double-check, not the primary safety net: any survivor here would mean
`_03_clean.py`'s own validation had a bug, not that `ST_CoverageClean`
itself misbehaved.

## Resilience

Each of the two detection queries (gap/overlap) falls back to an empty
result for that one kind (logged) on a GEOS failure, rather than raising --
consistent with `match`'s "failed group is logged and dropped, not fatal"
precedent, applied per-detection-kind here instead of per-group.

A precision-reduction retry (via `ST_ReducePrecision`) is not used as a
fallback here or in the fix stage -- the actual driver of the
coverage-clean instabilities once observed here was
`coverage_clean()`'s named-argument bug (see
`docs/adr/0003-st-coverageclean-positional-args.md`), not floating-point
precision, so there's no remaining case for a second, unvalidated retry
lever that silently perturbs input geometry.

## Portolan-scale profiling

Real admin-boundary layers, `--debug`, Apple Silicon/10 logical cores (run
before sliver detection/reporting was removed; the wall time/RSS figures
below no longer include a sliver-detection pass, which was the most
expensive part of `_02_issues` at scale -- expect faster/lighter runs now):

| Dataset            | fids  | Wall time | RSS peak   | Gap/overlap defects found |
| ------------------ | ----- | --------- | ---------- | -------------------------- |
| Burundi admin2     | 122   | 1.1s      | 118 MB     | 0                           |
| Chile admin3       | 345   | 132s      | 1.07 GB    | 0                           |
| Indonesia admin3   | 7,069 | 503s      | 1.58 GB    | 8 gap                       |
| Philippines admin3 | 1,642 | 396s      | **5.15 GB**| 16 gap                      |

This run surfaced and fixed two scale bugs in `_02_issues.py`'s
`_build_overlaps`, both only visible past a few thousand fids: the overlap
join predicate was too permissive, and the self-join ran against a wide
table instead of a narrow projection. See
`docs/adr/0011-overlap-detection-scale-bugs.md`.

**Philippines admin3 exceeded the 4 GB container target** (5.15 GB peak) on
this run, driven mostly by the (since-removed) sliver-detection pass in the
`issues` stage; gap/overlap detection alone is expected to be substantially
lighter. `clean` has no resampling knob to fall back on (nor does `extend`
anymore — see `docs/explanation/voronoi-memory.md`), so per this repo's "document, don't
gate" policy this is noted here rather than runtime-checked.
