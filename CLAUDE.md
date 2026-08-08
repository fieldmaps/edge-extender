# CLAUDE.md

## Project Overview

`topo-tools` is a Python package of DuckDB-powered geospatial topology utilities,
`pip install`-able and importable, mirroring the organization of the sister JS app
at `../topo-tools` (a DuckDB-WASM web app with the same tools). It ships five
tools, all used for improving administrative boundary datasets and matching
sub-national boundaries to national boundaries (import-linter contracts
governing which tool may depend on which are in `docs/reference/shared.md`):

- **extend**: extends polygon boundaries outward using Voronoi diagrams, producing a complete coverage layer that fills gaps (coastlines, disputed areas, water bodies).
- **match**: fits a child polygon layer into a coarser parent/clip layer (e.g. admin4 into admin0) by assigning each child to the parent it shares the largest area with, then running `extend`'s pipeline per group and clipping to that group's parent.
- **mosaic**: fits an already-extended child layer (a prior `extend()` output) into a new/different parent/clip layer, reusing `match`'s assignment logic but skipping Voronoi extension entirely. See `docs/explanation/mosaic.md`.
- **clean**: detects/fixes coverage defects (gaps, overlaps) in a single polygon layer with `ST_CoverageClean`, reporting them in a separate issues file for manual review. See `docs/explanation/clean.md`.
- **change**: compares an old/new polygon layer pair and classifies every unit (unchanged/renamed/modified/relocated/split/merge/complex/created/removed) via spatial overlap and optional code/name identity linking; writes a tabular changelog plus a colored spatial overlay layer. See `docs/explanation/change.md`.

## Deployment Targets

The pipeline targets two memory-constrained environments: **DuckDB-WASM in
the browser** (no disk, JS heap only — the Python pipeline documents the SQL
approach for eventual JS/TS porting) and **memory-limited containers**
(typically 2–4 GB RAM, no swap; pip-install this package into whatever image
you need — no Dockerfile ships here). Prefer approaches that minimize
intermediate materializations, avoid platform-specific calls (`os.sysconf`,
`/proc`, `subprocess`), and work with small buffer budgets.

## Architecture

Each tool's pipeline is a sequence of stages, each a standalone module in its
own `topo_tools/core/{tool}/` package. All stages of one `extend()`/`match()`
call share a single file-backed DuckDB connection; tables are the IPC
mechanism between stages (per-group subprocesses inside `match` are the one
exception — see `docs/explanation/match.md`). Three layers, each with a specific job
(mirroring `geoparquet-io`'s `core`/`api`/`cli` split):

- `topo_tools/core/{extend,match,mosaic,clean,change}/` — stage
  implementations. `core.match`/`core.change` import from `core.extend`
  (reusing its Voronoi-pipeline stage functions); `core.mosaic` imports from
  both `core.extend` (loader) and `core.match` (assign); all five may import
  the neutral leaf modules
  `core.constants`/`core.coverage`/`core.io`/`core.duckdb_utils`/`core.clip`.
- `topo_tools/api/{extend,match,mosaic,clean,change}.py` — public API
  functions; each chains its own tool's stages for exactly one file (or
  file pair) per call, except `mosaic`'s children role, which MAY span
  multiple files (see `docs/reference/mosaic.md`).
- `topo_tools/cli/main.py` — the click CLI, mapping flags/env vars onto one
  `api.*()` call per invocation, one file (or pair) at a time — `mosaic`'s
  child argument alone MAY be a glob pattern — no directory batching.

Import boundaries between these layers, and between tools, are mechanically
enforced by `pyproject.toml`'s import-linter contracts — see
`docs/reference/shared.md` for the MUST/MAY rules.

### Pipeline, Configuration & Table Naming

Each tool's stages are numbered modules in its own `topo_tools/core/{tool}/`
package (`_01_...py`, ...), each with its own docstring; behavior contracts
live in `docs/reference/{tool}.md`, stage-by-stage detail in
`docs/explanation/{tool}.md`.

Settings flow in as plain keyword arguments on each tool's own `api.*()`
function, mapped 1:1 from CLI flags/env vars — no module-level `argparse`/env
parsing anywhere. Common settings (`tmp_dir`, `threads`, `overwrite`,
`debug`, `step`) are in `docs/reference/shared.md`; per-tool
paths/arguments/`step` values are in `docs/reference/{tool}.md`
(`docs/explanation/change.md` pending its own reference file). Pure literals
live in `topo_tools/core/{tool}/_constants.py` and `topo_tools/core/constants.py`.

Tables are named `{name}_{stage}[suffix]`: no suffix means one persistent
table; a letter suffix (`_03a`, `_03b`) means multiple and **all** get a
letter, never one left bare; `_tmp{n}` is dropped before the function
returns, invisible unless `--debug`. Each tool uses its own `name` (e.g.
`{input}_match`) so tools never collide on the same input/`tmp_dir`;
per-tool table names are in `docs/explanation/{tool}.md`.

### Key Patterns

- **DuckDB spatial extension** handles all geometry operations (`ST_*` functions), one file-backed connection per input file (`topo_tools/core/duckdb_utils.py`), returned as a `ProfiledConnection` proxy that logs timing/memory per query when `--debug` is set.
- **DuckDB tables as IPC** — stages read and write named tables on the shared connection; no Parquet between stages.
- **Topology validation** (`_check_overlaps`/`_check_gaps` in each tool's outputs stage, backed by `has_coverage_violations` in `topo_tools/core/coverage.py`) always unnests MultiPolygons first. No byte-exactness check — see the next bullet.
- **Geometry column names**: `geom` in DuckDB tables, `geometry` in final output. `duckdb_memory()` profiling caveats are in `docs/explanation/performance.md`.
- **`_05_merge.py` joins against nearby originals via bbox-prefiltered, part-exploded join, never a global `ST_Union_Agg` operand** (`_02_lines.py`'s neighbor-union join uses whole-fid bboxes instead — not interchangeable). See `docs/adr/0001-avoid-global-union-agg-operand.md`.
- **Never call `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` inline inside a JOIN's `ON` clause** — DuckDB recomputes the envelope per pairwise comparison instead of once per row, which can hang indefinitely on a table with even a few very-high-vertex-count polygons. Precompute bbox columns on the joined table/CTE first, as `_05_merge.py` already does (see `docs/adr/0014-bbox-inline-recompute-in-join.md`).
- **Byte-exact preservation of original polygon vertices is not a goal.** `ST_CoverageClean` may shift any polygon's boundary, including previously-untouched ones (see `docs/explanation/topology.md`).
- **`match` reuses `extend`'s stage functions per-group** (so `extend` stays usable standalone) **in an isolated subprocess**, not `match()`'s own process — GEOS's native heap isn't fully released between files even after closing the DuckDB connection. See `docs/explanation/match.md`.
- **`mosaic` skips Voronoi extension entirely** — it assumes the child layer is already a finished `extend()` output, reuses `match`'s assign step and the shared `core/clip.py` leaf (also used by `match`) for clip+merge, no per-group subprocess for extension itself. See `docs/explanation/mosaic.md`.
- **`core/clip.py`'s `assign_table` branch clips one parent fid at a time, each in its own spawned subprocess, boundary adaptively grid-tiled before intersecting.** Repeated plain `ST_Intersection` leaks GEOS's native heap the same way `extend()`'s Voronoi machinery does, and a single oversized parent (many children against a highly complex boundary) can itself exceed available memory even fully isolated; tile size is solved from each parent's own vertex density rather than a fixed constant, and small parents skip tiling entirely (see `docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`).
- **`core.clean` depends only on the shared leaf modules, not `core.extend`.** See `docs/explanation/clean.md`.
- **`ST_CoverageClean`'s `gap_maximum_width` has no GEOS-native auto-fill default.** `clean`'s `--gap-width auto` mode computes an explicit width from the widest thin detected gap; `all` mode uses a fixed `GAP_MAXIMUM_WIDTH_ALL_DEG = 360` sentinel (see `docs/adr/0002-gap-maximum-width-no-native-default.md`).
- **`coverage_clean()` (`core/coverage.py`) must call `ST_CoverageClean` positionally, never via DuckDB's `:=` named-argument syntax.** DuckDB binds named arguments to compiled/extension scalar functions purely by position, silently discarding the name (see `docs/adr/0003-st-coverageclean-positional-args.md`).
- **`ST_Distance(GEOMETRY, GEOMETRY)` is unreliable for two disjoint polygons at small separations.** Use `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or `ST_MaximumInscribedCircle` instead (see `docs/adr/0004-st-distance-unreliable-near-disjoint.md`).
- **`clean/_02_issues.py`'s per-detection-kind retry falls back to an empty result table (logged) if both attempts fail, rather than leaving the table missing.** Any new call site of `_run_with_retry` must supply `empty_sql` (see `docs/adr/0005-clean-retry-fallback-bug.md`).
- **`change`'s classification runs in Python (`core/change/_03_classify.py`), not SQL** — feature-count-scaled, not vertex-scaled, unlike `extend`/`clean`'s work. See `docs/explanation/change.md`.
- **`change` always uses exact `ST_Intersection`, never point-sampling** — unlike the sister JS app's WASM-only-bug workaround. See `docs/explanation/change.md`.
- **`clean`'s `--maximum-gap-width`/`--snapping-distance` are decimal degrees, not meters** (`_01` is always EPSG:4326). See `docs/explanation/clean.md`.

### Supported Formats

Input/output: GeoParquet (`.parquet`), GeoPackage (`.gpkg`), Shapefile (`.shp`), GeoJSON (`.geojson`). Output format matches input format.

## Commands

```bash
# Install dependencies
uv sync

# Run the extend tool (processes exactly one file per call)
uv run topo-tools extend example.geojson
# equivalently: uv run python -m topo_tools extend example.geojson

# Run the match tool (fits a child layer into a parent/clip layer)
uv run topo-tools match children.geojson parents.geojson

# Run the mosaic tool (re-clips an already-extended child layer into a new parent layer)
uv run topo-tools mosaic extended_children.parquet new_parents.geojson

# Run the clean tool (detects/fixes gaps+overlaps, reports issues separately)
uv run topo-tools clean example.geojson

# Run the change tool (compares an old/new polygon layer pair)
uv run topo-tools change old.geojson new.geojson

# Format and lint
uv run ruff format && uv run ruff check
```

Pre-commit hooks run `uv-sync`, `ruff-format`, and `ruff-check` automatically.

## Test Datasets

| Dataset | Use |
| --- | --- |
| **West Africa cluster** (`sen`/`gmb`/`gnb`/`gin`/`civ`/`gha`/`tgo`/`ben`, portolan `adm2`) | Mutually neighboring countries — single-file tool tests (extend/match/clean/change) and mosaic's multi-file combine test |

A full portolan catalog (real, large-scale admin boundary data, multiple
countries and admin levels, some with multiple historical versions) is
available for at-scale/real-data stress testing beyond the cluster above:

- **Local copy**: `/Users/computer/GitHub/OCHA-DAP/hdx-scraper-cod-ab-global/portolan`
- **Live/canonical source**: [source.coop/hdx/cod-ab](https://source.coop/hdx/cod-ab),
  STAC root catalog at `https://data.source.coop/hdx/cod-ab/catalog.json`
  (`id: portolan`; per-country `child` links, e.g. `./chl/catalog.json`)

**HARD RULE — the portolan catalog (local copy or live source) is read-only.**
Never write, modify, move, or delete anything inside
`/Users/computer/GitHub/OCHA-DAP/hdx-scraper-cod-ab-global/portolan` — no
`--output-path`/`--overwrite`, no `--tmp-dir`, no `--debug` exports, nothing.
Only ever read from it. Every output/tmp/debug path for a portolan-sourced
test run must point outside the catalog (e.g. the session scratchpad or
`/tmp`).

See `docs/how-to/at-scale-testing.md` for the STAC layout and how to pick a
file (or an old/new comparison pair, for `change`) from the catalog.

## Reference Docs

- `docs/reference/` — behavior contracts per tool (`shared.md` for common settings/gates)
- `docs/explanation/extend.md` — Voronoi-extension algorithm, stage-by-stage detail
- `docs/explanation/topology.md` — ST_Node/ST_Polygonize approach, spatial function reference, SPATIAL_JOIN memory bug
- `docs/explanation/match.md` — assignment algorithm, subprocess isolation, `check_gaps` caveat
- `docs/explanation/mosaic.md` — reuse of match's assign + shared clip leaf, match-vs-mosaic comparison, overshoot/cross-provenance caveats
- `docs/explanation/clean.md` — defect detection, `ST_CoverageClean` semantics, issues-file schema
- `docs/explanation/change.md` — overlap/classification algorithm, output schema, two-file design
- `docs/explanation/performance.md` — thread-scaling benchmarks, phase profiles, RTREE experiment
- `docs/explanation/voronoi-memory.md` — per-file resampling distance, memory ceilings for `phl_admin3`/`idn_admin3`
- `docs/how-to/publishing.md` — PyPI release process (GitHub Release → OIDC trusted publisher)
- `docs/how-to/verify-duckdb-function.md` — DuckDB/spatial function lookup commands
- `docs/how-to/at-scale-testing.md` — portolan catalog layout, picking a file or old/new pair for a real-scale test
- `docs/adr/README.md` — how to decide whether a fact belongs in an ADR vs. `docs/explanation/` vs. CLAUDE.md's Key Patterns
- `docs/adr/` — immutable decision records referenced from Key Patterns above
