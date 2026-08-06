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
3. **`_03_clean`** -- fixes gaps/overlaps via `ST_CoverageClean` (gated: a
   no-op copy only if the input has no coverage violations *and* no detected
   gap qualifies to fill under the resolved `gap_maximum_width` -- see
   "`has_coverage_violations()` alone cannot stand in for gap detection"
   below; that check is only about overlaps/mismatched edges, so a gap-only
   input still needs `ST_CoverageClean` to actually run), retrying the
   resolved `gap_maximum_width` through an escalation ladder if the result
   still has invalid edges (see "gap_maximum_width escalation" below).
4. **`_04_outputs`** -- validates overlaps are gone (hard gate), logs
   (never raises on) any gaps still unfilled by design, and exports both the
   cleaned dataset and the issues report.

## Skipping overlap detection when the coverage is already valid

`_02_issues.py`'s `_build_overlaps` (bbox-prefiltered O(n^2) self-join) was
the dominant cost of a `clean` run on an already-clean dataset -- confirmed
on a real 9,658-fid admin4 layer: the full `clean` CLI run took ~20 minutes
even though the input had zero defects, because overlap detection ran
unconditionally regardless of whether anything was actually wrong.

`main()` now checks `has_coverage_violations()` (`ST_CoverageInvalidEdges_Agg`,
the shared `core/coverage.py`) before running `_build_overlaps`, and writes an
empty overlaps table directly when it's already False -- ~5s on the
9,658-fid layer, versus minutes for the equivalent self-join, since a
coverage with no invalid edges cannot contain an overlapping or nested pair
either.

Gap detection (`_build_gaps`) always runs regardless -- unlike overlaps,
there's no cheaper GEOS primitive that answers "are there any gaps" without
doing the same whole-table union `_build_gaps` itself needs to actually
extract them, so there's nothing to gate it on. An earlier version of this
optimization added a separate `has_gaps()` pre-check ahead of `_build_gaps`
to decide whether to skip it too; that pre-check computed its own
whole-table union just to return a boolean, which `_build_gaps` then
recomputed from scratch whenever gaps actually existed -- paying for the
union twice with no benefit. Letting `_build_gaps` run unconditionally
avoids that duplication and costs the same as the union alone: ~18s on the
9,658-fid layer, giving the same ~23s total (5s + 18s) for a fully clean
dataset as the discarded approach, but without the wasted extra union on a
dataset that actually has gaps.

**`has_coverage_violations()` alone cannot stand in for gap detection** --
verified empirically with a synthetic fixture (a pinwheel of 4 valid,
edge-matched polygons fully surrounding a real 1x1 hole): it returned
`False` even though a genuine fully-enclosed gap existed. It only detects
overlaps/mismatched edges, never gaps. `_03_clean.py`'s fix-stage gate used
to rely on this check alone to decide whether `ST_CoverageClean` was worth
running at all, which meant a gap-only input (no overlaps) was silently
never fixed despite being correctly reported in the issues file -- the gate
now also checks whether any detected gap qualifies to fill under the
resolved `gap_maximum_width` (see "Pipeline" above).

## Sliver detection/fixing was removed

Earlier versions of this tool also detected (but never auto-fixed) slivers
-- near-miss boundary mismatches, via
`ST_CoverageInvalidEdges_Agg(geom, tolerance)`. It was dropped entirely:

- **Never fixable in the first place.** Auto-snapping a near-miss sliver
  closed requires widening `ST_CoverageClean`'s `snapping_distance`
  parameter, which re-nodes the **whole** coverage, not just the defect
  site -- silently perturbing unrelated, already-correct geometry elsewhere
  in the file. That's an unacceptable side effect for something running
  unattended in a batch pipeline, so sliver "fixing" was never on the table;
  the JS sister app reversed the same way early in its own history (commit
  `9e57932`, "slivers detection-only; remove snap and Changes feature").
- **Detection itself was not reliable enough to keep as report-only,
  either.** The gap/overlap-subtraction step in the detection query (buffer
  + cross join + `ST_Difference` against unioned blobs) reproducibly
  triggered a DuckDB out-of-memory error on real data -- confirmed on Angola
  admin1 (`hdx-cod-ab-ai`'s `ago_admin1.parquet`, only 21 fids / 490K
  vertices, nowhere near the scale where `extend`'s known memory ceilings
  kick in). It was disabled by default (`--sliver-tolerance 0`) for this
  reason before removal. Given detection alone couldn't be trusted at even
  tiny real-world scale, and there was no fix path to justify the risk, the
  whole feature (flag, detection query, issues-file `kind='sliver'` rows)
  was removed rather than kept behind an opt-in flag.

Any near-miss boundary mismatch is now an upstream data-quality issue,
outside this tool's scope -- fixing it (re-digitizing the source, or manual
editing in QGIS/ArcGIS) remains a human decision, same as before, just
without an automated detector flagging candidates.

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
  `ST_CoverageClean` with DuckDB's own named arguments,
  `gap_maximum_width := ...` / `snapping_distance := ...` (verified live via
  `duckdb_functions()`) -- a Python `None` omits the argument entirely
  rather than passing a sentinel. The CLI/API layer (`--maximum-gap-width`,
  `--snapping-distance`, and the matching `api.clean.clean()` kwargs)
  instead follows GDAL's `gdal vector clean-coverage` word order for the gap
  one, since that's what a human actually types; `api.clean.clean()` is the
  one place the two namings meet.
- `ST_CoverageClean`'s gap-merge only fills **fully-enclosed** holes -- a
  ring of polygons surrounding missing area (a lake, a missing admin unit).
  An open "inlet" gap between two side-by-side, non-enclosing polygons is
  left untouched regardless of `gap_maximum_width` (confirmed empirically
  with an isolated 2-polygon fixture: identical output whether
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
  plus a small epsilon (`ALL_GAP_WIDTH_EPSILON_FACTOR` in `_constants.py`)
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
- `all` -- fills every gap the detection stage found. Computed the same way
  as `auto`'s width, but over *every* detected gap, not just thin ones
  (`max((ST_MaximumInscribedCircle(geom)).radius * 2) FROM {name}_02 WHERE
  kind='gap'`), plus the same small epsilon. A fixed "just make it huge"
  constant was tried and rejected: `gap_maximum_width` in the
  single-digit-degrees range and up was confirmed to make
  `ST_CoverageClean` silently erode or entirely erase real polygon area on
  a real admin-boundary layer (164 fids, 190km² input down to 50km² at 10
  degrees, fully empty at 20+) -- not just close gaps, destroy data. There
  is no width that's both "definitely wide enough to fill everything" and
  "definitely safe"; the widest *actually detected* gap plus a small
  epsilon is the only value with any principled justification.
- A bare number is an explicit cap in decimal degrees, passed straight
  through to `ST_CoverageClean` with no conversion.

## `gap_maximum_width` escalation on a coverage-clean instability

`ST_CoverageClean` has two confirmed real failure modes tied to
`gap_maximum_width`, independent of `snapping_distance` (varying
`snapping_distance` alone across 8 orders of magnitude never fixed either
one; only the exact `gap_maximum_width` value mattered):

1. **Residual invalid edges, or an outright `TopologyException`**, at
   certain widths -- confirmed against a real admin-boundary defect where
   the failure was narrow and non-monotonic (good/bad/good/**crash**/bad/
   good across a ~24m span), not a simple threshold.
2. **Silent area erosion**, once the width approaches the scale of the
   data's own local topology (see the `all` mode note above) -- confirmed
   both on real data at multi-degree widths and, more surprisingly, on a
   small synthetic fixture at a width exactly matching one of its own real
   gaps, when combined with a second, differently-scaled group in the same
   `ST_CoverageClean` call (each group alone was fine; several unrelated
   polygons in the combined call collapsed to zero area). This one isn't
   fully understood -- treated as a real, narrow `ST_CoverageClean` quirk
   worth a closer look or an upstream bug report, not something papered
   over here.

`_03_clean.py`'s `main()` retries the resolved target width (from
`auto`/`all`/an explicit value) through `GAP_WIDTH_ESCALATION_FACTORS`
(`_constants.py`: `1.0, 1.001, 1.002, 1.005, 1.01, 1.02, 1.05, 1.10, 1.20`),
validating each attempt against **both** `has_coverage_violations()` *and*
a total-area sanity floor (`AREA_SANITY_FACTOR = 0.8`) -- the invalid-edges
check alone passes a totally empty result as "no violations," confirmed
directly, so it cannot catch failure mode 2 on its own. Each rung only
ever multiplies the *original* target upward, never below it, so
`auto`/`all`/explicit semantics are preserved: a wider cap can only fill
*more* gaps, never fewer, so the gap that was actually asked for stays
filled. The ladder is sized with real margin above the one confirmed
invalid-edges case (a ~36m-wide instability that cleared at +1.0%) -- the
last three rungs (+5%, +10%, +20%) are pure safety margin beyond anything
actually observed needing escalation. Validated end-to-end against the
real admin-boundary stress case in both `auto` and `all` modes: output
area matches input to within ~0.0003km² out of ~190km² (the expected,
tiny overlap-dedup delta), not the catastrophic loss failure mode 2
produces.

If every rung still fails, `main()` raises rather than silently falling
back to a different gap-filling behavior (e.g. disabling gap-filling
entirely) -- retrying with an unrelated, unvalidated parameter change
risks masking a genuine, dataset-specific GEOS edge case as a routine one,
and the human running `clean` deserves to know a specific input triggered
something unusual rather than getting output that quietly differs from
what they asked for.

### The total-area floor alone misses a small, localized collapse

`AREA_SANITY_FACTOR` only bounds the *summed* output area, so a single
small feature collapsing entirely can hide inside it if the rest of the
dataset is much larger. Each escalation attempt is also checked per fid:

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
  whose fixed geometry isn't a `POLYGON`/`MULTIPOLYGON` fails this rung.

Both checks compare against exact, defect-derived bounds rather than a
guessed percentage floor -- a percentage floor on a per-fid basis was tried
and rejected, since full containment (one fid entirely absorbed by another)
and gap-neighborhood redistribution are both legitimate 100%-loss outcomes
for the fid actually involved.

## `--snapping-distance auto|<degrees>`

`auto` omits the argument from the `ST_CoverageClean` call, keeping GEOS's
real computed default. An explicit value (decimal degrees, passed straight
through) overrides it. This is a **noding-robustness knob only** -- per
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
floating-point noise floor is applied. An earlier version discarded
anything below `MIN_ISSUE_AREA_M2` (`1e-4 m^2`, ~1cm^2), ported directly
from topo-tools-js's own noise floor -- itself sized to a float-jitter
magnitude (up to `1.6e-7 m^2`) observed in that app's WASM-compiled GEOS
build, never independently measured against this native pipeline.

Verified directly: running this pipeline's exact gap- and
overlap-detection queries with the floor removed against five real/
synthetic already-clean inputs -- two hand-built synthetic fixtures, a
real 9,658-fid COD admin4 layer, and Chile/Philippines/Indonesia admin3's
`extended.parquet` (full-pipeline output -- `ST_MakeValid` ->
`ST_Transform` -> Voronoi merge -> whole-table `ST_CoverageClean`, each
confirmed `has_coverage_violations() == False`) -- found zero
floating-point artifacts on either detection path. The overlap join
predicate itself (`ST_Overlaps`/`ST_Contains`) never matched a candidate
pair on any of these valid coverages, since it requires true interior
intersection, not mere boundary-touching, so `ST_Intersection` never even
ran on a real candidate. Consistent with `docs/change.md`'s documented
WASM-only GEOS `OverlayNG` bug that doesn't reproduce natively: constants
tuned against topo-tools-js's WASM-compiled GEOS build don't necessarily
carry over to this native pipeline without independent verification.

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
the time `_04_outputs.py` runs it, `_03_clean.py`'s own gap_maximum_width
escalation (see above) has already validated `{name}_03` has no invalid
edges -- or raised before returning. This check is now a defensive
double-check, not the primary safety net: any survivor here would mean
`_03_clean.py`'s own validation had a bug, not that `ST_CoverageClean`
itself misbehaved.

## Resilience

Each of the two detection queries (gap/overlap) falls back to an empty
result for that one kind (logged) on a GEOS failure, rather than raising --
consistent with `match`'s "failed group is logged and dropped, not fatal"
precedent, applied per-detection-kind here instead of per-group.

A precision-reduction retry (via `ST_ReducePrecision`) is not used as a
fallback here or in the fix stage. The confirmed driver of `ST_CoverageClean`
instability is `gap_maximum_width` (see "gap_maximum_width escalation on a
coverage-clean instability" above), not floating-point precision --
escalating that value is the validated lever, so a second, unvalidated one
that silently perturbs input geometry adds risk without addressing the
actual cause.

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

Two real bugs surfaced and fixed by this run (`_02_issues.py`'s
`_build_overlaps`), both only visible past a few thousand fids:

1. **Overlap join predicate was `ST_Intersects`, not `ST_Overlaps`/
   `ST_Contains`.** `ST_Intersects` is true for any pair of polygons that
   merely share a boundary edge -- the normal case for every adjacent pair in
   a coverage layer, not a defect. On Indonesia admin3 (7,069 fids) this
   matched 18,457 candidate pairs, each still paying for `ST_Intersection` +
   `ST_MakeValid` + `ST_CollectionExtract`, and the stage did not finish in
   6+ minutes. Switched the join predicate to `ST_Overlaps(a, b) OR
   ST_Contains(a, b) OR ST_Contains(b, a)` -- `ST_Overlaps` alone would miss
   a fully-duplicated or nested polygon pair (OGC: its intersection equals
   one/both inputs, so `ST_Overlaps` is false by definition), hence the
   `ST_Contains` half. Regression test:
   `test_clean_detects_full_containment_overlap` in `tests/test_clean.py`.
2. **Self-joining the wide `_01` table (36 columns for real admin data)
   instead of a narrow `(fid, geom)` projection made DuckDB fall back to
   near-single-threaded execution**, even though the join only references
   `fid`/`geom`. Confirmed on Indonesia admin3: the join against `_01` ran at
   ~99% CPU; the identical join against a narrow projection of the same rows
   ran at ~420% CPU. `_build_overlaps` now always projects to
   `{table}_narrow` before joining.

**Philippines admin3 exceeded the 4 GB container target** (5.15 GB peak) on
this run, driven mostly by the (since-removed) sliver-detection pass in the
`issues` stage; gap/overlap detection alone is expected to be substantially
lighter. `clean` has no resampling knob to fall back on (nor does `extend`
anymore — see `docs/voronoi-memory.md`), so per this repo's "document, don't
gate" policy this is noted here rather than runtime-checked.
