# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `clean`: the fix-stage escalation loop now also rejects a rung if any fid
  with no detected defect of its own (not touching a filled gap, not party
  to an overlap) came out with a materially different area, or if any
  fid's fixed geometry isn't a Polygon/MultiPolygon. The existing total-area
  sanity floor only checks the summed total, so a single small feature
  collapsing (or degenerating into a stray line via a mixed
  `GEOMETRYCOLLECTION`) could pass it if the rest of the dataset is much
  larger. Defect-involved fids are exempt rather than held to a percentage
  floor, since `ST_CoverageClean` can legitimately redraw a whole neighborhood
  around a fix (confirmed: filling a gap fully reassigned two small,
  overlap-uninvolved connector strips into a third fid), and full
  containment is a legitimate 100%-loss outcome for the absorbed fid.
- `clean`: the fix stage now logs the accepted result's total area change
  (gained/lost, as a percentage) on every successful run, not just on
  escalation or failure.
- `clean`: the issues report now includes the actual measured outcome of
  the fix for every row, not just the defect as detected:
  `unit_a_area_change_m2`/`unit_b_area_change_m2` (each named unit's own
  real area change) for overlap rows, `filled_area_m2` (how much of the
  gap's own area ended up covered) for gap rows.

### Fixed

- `clean`: the fix stage no longer skips `ST_CoverageClean` entirely on a
  gap-only input (no overlaps at all). The gate previously relied on
  `has_coverage_violations()` alone, which never detects gaps, so a
  correctly-detected, fillable gap could sit in the issues file forever
  without ever actually being fixed. The gate now also checks whether any
  detected gap qualifies to fill under the resolved `gap_maximum_width`.

### Changed

- `clean`: `--maximum-gap-width` now defaults to `auto` (fill only
  thin/sliver-shaped gaps) instead of `all` (fill every detected gap).
  `all` remains available as an explicit opt-in.
- **Breaking:** `clean`: `--maximum-gap-width`/`--snapping-distance` (and
  the matching `api.clean.clean()` kwargs) now take decimal degrees instead
  of meters, the units `ST_CoverageClean` itself takes on our
  always-EPSG:4326 data, and the same convention GDAL/OGR uses for distance
  parameters on an unprojected layer. Removes a dataset-wide
  `cos(centroid latitude)` conversion that was a real approximation over
  large north-south extents. See `docs/clean.md`.
- `clean`: `_03_clean.py` now retries the resolved `gap_maximum_width`
  (from `auto`/`all`/an explicit value) through a validated escalation
  ladder (widening only, never below the original target) if
  `ST_CoverageClean` leaves residual invalid edges, raises, or silently
  erodes real polygon area (two confirmed real `ST_CoverageClean` failure
  modes), unrelated to `snapping_distance`. Validation now checks both
  `has_coverage_violations()` and a total-area sanity floor, since the
  former alone passes a totally empty result as "no violations." If every
  rung fails, `clean` now raises a clear, actionable error instead of the
  previous bare `OVERLAPS: {table}`. `--maximum-gap-width all`'s width is
  still computed from the widest actually-detected gap (unchanged
  behavior). A fixed large constant was tried during development and
  rejected after it was shown to make `ST_CoverageClean` erase real
  polygon area on real data. See `docs/clean.md`.

### Removed

- `clean`: the `MIN_ISSUE_AREA_M2` (~1cm²) floating-point noise floor on
  detected gaps/overlaps. Ported from topo-tools-js's own WASM-tuned
  constant; empirical testing against this native pipeline (a real
  9,658-fid COD admin4 layer, plus Chile/Philippines/Indonesia admin3's
  full-pipeline `extended.parquet` output) found zero floating-point
  artifacts on either detection path with the floor removed. `clean` now
  reports every detected gap/overlap regardless of size. See
  `docs/clean.md`.
- `clean`: sliver detection/reporting (`--sliver-tolerance`, issues-file
  `kind='sliver'` rows). Detection was unreliable even at tiny real-data
  scale (OOM confirmed on a 21-fid Angola admin1 file) and slivers were
  never auto-fixable in the first place (see `docs/clean.md`). `clean` now
  only detects/fixes gaps and overlaps.
- `extend`/`match`: `--memory-gb`. It only ever sized `attempt.py`'s
  Voronoi resampling distance. Other stages (`_01_inputs`, `_02_lines`,
  the whole-table `_05_merge`/`_04_merge` coverage-clean pass) have no
  resampling lever and routinely exceed whatever ceiling was declared
  anyway (documented cases up to ~5.9GB against a 4GB target), so the flag
  gave a false sense of a memory guarantee the pipeline never actually
  provided. The starting resampling distance is now always
  `min(DEFAULT_DISTANCE, natural_res)`; the existing doubling-retry loop
  still handles any resulting failure the same way it always did, see
  `docs/voronoi-memory.md`.

## [0.1.0] - 2026-07-10

Initial release: four tools, CLI + Python API for each.

- `extend`: Voronoi-based polygon boundary extension, producing a complete
  coverage layer that fills gaps.
- `match`: fits a child polygon layer into a coarser parent/clip layer by
  largest-overlap assignment, then runs `extend`'s pipeline per group.
- `clean`: detects and fixes coverage gaps/overlaps via `ST_CoverageClean`;
  detects (but never auto-fixes) slivers, reported separately for review.
- `change`: compares two versions of a polygon layer and classifies every
  unit as unchanged/renamed/modified/relocated/split/merge/complex/created/
  removed, via spatial overlap and optional code/name identity linking.

[Unreleased]: https://github.com/OCHA-DAP/topo-tools-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OCHA-DAP/topo-tools-py/releases/tag/v0.1.0
