# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `clean`: `--maximum-gap-width` now defaults to `auto` (fill only
  thin/sliver-shaped gaps) instead of `all` (fill every detected gap).
  `all` remains available as an explicit opt-in.

### Removed

- `clean`: sliver detection/reporting (`--sliver-tolerance`, issues-file
  `kind='sliver'` rows). Detection was unreliable even at tiny real-data
  scale (OOM confirmed on a 21-fid Angola admin1 file) and slivers were
  never auto-fixable in the first place -- see `docs/clean.md`. `clean` now
  only detects/fixes gaps and overlaps.
- `extend`/`match`: `--memory-gb`. It only ever sized `attempt.py`'s
  Voronoi resampling distance -- other stages (`_01_inputs`, `_02_lines`,
  the whole-table `_05_merge`/`_04_merge` coverage-clean pass) have no
  resampling lever and routinely exceed whatever ceiling was declared
  anyway (documented cases up to ~5.9GB against a 4GB target), so the flag
  gave a false sense of a memory guarantee the pipeline never actually
  provided. The starting resampling distance is now always
  `min(DEFAULT_DISTANCE, natural_res)`; the existing doubling-retry loop
  still handles any resulting failure the same way it always did -- see
  `docs/voronoi-memory.md`.

## [0.1.0] - 2026-07-10

Initial release: four tools, CLI + Python API for each.

- `extend` — Voronoi-based polygon boundary extension, producing a complete
  coverage layer that fills gaps.
- `match` — fits a child polygon layer into a coarser parent/clip layer by
  largest-overlap assignment, then runs `extend`'s pipeline per group.
- `clean` — detects and fixes coverage gaps/overlaps via `ST_CoverageClean`;
  detects (but never auto-fixes) slivers, reported separately for review.
- `change` — compares two versions of a polygon layer and classifies every
  unit as unchanged/renamed/modified/relocated/split/merge/complex/created/
  removed, via spatial overlap and optional code/name identity linking.

[Unreleased]: https://github.com/fieldmaps/topo-tools-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fieldmaps/topo-tools-py/releases/tag/v0.1.0
