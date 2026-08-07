# CLAUDE.md

## Verification Over Recall

- For DuckDB/spatial functions specifically, see `docs/how-to/verify-duckdb-function.md` for the lookup commands (CLI + `gh api`)

## Project Overview

`topo-tools` is a Python package of DuckDB-powered geospatial topology utilities,
`pip install`-able and importable, mirroring the organization of the sister JS app
at `../topo-tools` (a DuckDB-WASM web app with the same tools). It ships four
tools, all used for improving administrative boundary datasets and matching
sub-national boundaries to national boundaries (import-linter contracts
governing which tool may depend on which are in `docs/reference/shared.md`):

- **extend**: extends polygon boundaries outward using Voronoi diagrams, producing a complete coverage layer that fills gaps (coastlines, disputed areas, water bodies).
- **match**: fits a child polygon layer into a coarser parent/clip layer (e.g. admin4 into admin0) by assigning each child to the parent it shares the largest area with, then running `extend`'s pipeline per group and clipping to that group's parent.
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

## Test Datasets

| Dataset                            | Use                                                                |
| ---------------------------------- | ------------------------------------------------------------------ |
| **Burundi** (`bdi_admin2.parquet`) | Small, fast — good for quick iteration                             |
| **Chile** (`chl_admin3.parquet`)   | Large coastline, most memory-intensive — the canonical stress test |

A full portolan catalog (real, large-scale admin boundary data, multiple
countries and admin levels, some with multiple historical versions) is
available for at-scale/real-data stress testing beyond the two fixtures
above:

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

STAC-like layout: `{iso3}/{latest,vNN}/{adm0..adm3,lines,points}/{original,
extended,matched}.parquet`. Distinct `vNN` dirs are always genuinely
different content; `latest` is whichever `vNN` is newest. Not every country
has 2+ `vNN` yet (e.g. Chile only `v01`) — check before picking an old/new
comparison pair; Philippines admin3 `v02`→`v03` is a real diff, used for
`change`'s first at-scale test.

## Commands

```bash
# Install dependencies
uv sync

# Run the extend tool (processes exactly one file per call)
uv run topo-tools extend example.geojson
# equivalently: uv run python -m topo_tools extend example.geojson

# Run the match tool (fits a child layer into a parent/clip layer)
uv run topo-tools match children.geojson parents.geojson

# Run the clean tool (detects/fixes gaps+overlaps, reports issues separately)
uv run topo-tools clean example.geojson

# Run the change tool (compares an old/new polygon layer pair)
uv run topo-tools change old.geojson new.geojson

# Format and lint
uv run ruff format && uv run ruff check
```

Pre-commit hooks run `uv-sync`, `ruff-format`, and `ruff-check` automatically.

## Architecture

Each tool's pipeline is a sequence of stages, each a standalone module in its
own `topo_tools/core/{tool}/` package. All stages of one `extend()`/`match()`
call share a single file-backed DuckDB connection; tables are the IPC
mechanism between stages (per-group subprocesses inside `match` are the one
exception — see `docs/explanation/match.md`). Three layers, each with a specific job
(mirroring `geoparquet-io`'s `core`/`api`/`cli` split):

- `topo_tools/core/{extend,match,clean,change}/` — stage implementations.
  `core.match`/`core.change` import from `core.extend` (reusing its
  Voronoi-pipeline stage functions); all four may import the neutral leaf
  modules `core.constants`/`core.coverage`/`core.io`/`core.duckdb_utils`.
- `topo_tools/api/{extend,match,clean,change}.py` — public API functions;
  each chains its own tool's stages for exactly one file (or file pair) per
  call.
- `topo_tools/cli/main.py` — the click CLI, mapping flags/env vars onto one
  `api.*()` call per invocation, one file (or pair) at a time, no directory
  batching.

Import boundaries between these layers, and between tools, are mechanically
enforced by `pyproject.toml`'s import-linter contracts — see
`docs/reference/shared.md` for the MUST/MAY rules.

### Pipeline, Configuration & Table Naming

Each tool's stages are numbered modules in its own `topo_tools/core/{tool}/`
package (`_01_...py`, ...), each with its own docstring; behavior contracts
live in `docs/reference/{tool}.md`, stage-by-stage detail in
`docs/explanation/{tool}.md`. Stage counts: **extend** 5, **match** 5,
**clean** 4, **change** 4.

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
- **Byte-exact preservation of original polygon vertices is not a goal.** `ST_CoverageClean` may shift any polygon's boundary, including previously-untouched ones (see `docs/explanation/topology.md`).
- **`match` reuses `extend`'s stage functions per-group** (so `extend` stays usable standalone) **in an isolated subprocess**, not `match()`'s own process — GEOS's native heap isn't fully released between files even after closing the DuckDB connection. See `docs/explanation/match.md`.
- **`core.clean` depends only on the shared leaf modules, not `core.extend`** — reuses `core.io.read_and_reproject()` and `core.coverage.coverage_clean()`, both tool-independent.
- **`ST_CoverageClean`'s `gap_maximum_width` has no GEOS-native auto-fill default.** `clean`'s `--gap-width auto` mode computes an explicit width from the widest thin detected gap; `all` mode uses a fixed `GAP_MAXIMUM_WIDTH_ALL_DEG = 360` sentinel (see `docs/adr/0002-gap-maximum-width-no-native-default.md`).
- **`coverage_clean()` (`core/coverage.py`) must call `ST_CoverageClean` positionally, never via DuckDB's `:=` named-argument syntax.** DuckDB binds named arguments to compiled/extension scalar functions purely by position, silently discarding the name (see `docs/adr/0003-st-coverageclean-positional-args.md`).
- **`ST_Distance(GEOMETRY, GEOMETRY)` is unreliable for two disjoint polygons at small separations.** Use `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or `ST_MaximumInscribedCircle` instead (see `docs/adr/0004-st-distance-unreliable-near-disjoint.md`).
- **`clean/_02_issues.py`'s per-detection-kind retry falls back to an empty result table (logged) if both attempts fail, rather than leaving the table missing.** Any new call site of `_run_with_retry` must supply `empty_sql` (see `docs/adr/0005-clean-retry-fallback-bug.md`).
- **`core.change` reuses `extend`'s `_01_inputs.main()`, but deliberately does not import `core.match`** — even though `_02_overlap.py` mirrors `_02_assign.py`'s pattern, `change` stays decoupled from `match`/`clean` too.
- **`EQUAL_AREA_CRS`/`SNAP_TOLERANCE` live in the shared `core/constants.py`**, not any one tool's `_constants.py` — `match`/`clean`/`change` all need one or both.
- **`change`'s classification runs in Python (`core/change/_03_classify.py`), not SQL** — feature-count-scaled, not vertex-scaled, unlike `extend`/`clean`'s work. See `docs/explanation/change.md`.
- **`change` always uses exact `ST_Intersection`, never point-sampling** — unlike the sister JS app's WASM-only-bug workaround. See `docs/explanation/change.md`.
- **`clean`'s `--maximum-gap-width`/`--snapping-distance` are decimal degrees, not meters** (`_01` is always EPSG:4326). See `docs/explanation/clean.md`.

### Supported Formats

Input/output: GeoParquet (`.parquet`), GeoPackage (`.gpkg`), Shapefile (`.shp`), GeoJSON (`.geojson`). Output format matches input format.

## Documentation Structure

`docs/` follows the Diátaxis split from the global CLAUDE.md; see
`docs/adr/README.md` for when a bullet belongs in `docs/adr/` instead of
here or in `docs/explanation/`.

## Reference Docs

- `docs/reference/` — behavior contracts per tool (`shared.md` for common settings/gates)
- `docs/explanation/extend.md` — Voronoi-extension algorithm, stage-by-stage detail
- `docs/explanation/topology.md` — ST_Node/ST_Polygonize approach, spatial function reference, SPATIAL_JOIN memory bug
- `docs/explanation/match.md` — assignment algorithm, subprocess isolation, `check_gaps` caveat
- `docs/explanation/clean.md` — defect detection, `ST_CoverageClean` semantics, issues-file schema
- `docs/explanation/change.md` — overlap/classification algorithm, output schema, two-file design
- `docs/explanation/performance.md` — thread-scaling benchmarks, phase profiles, RTREE experiment
- `docs/explanation/voronoi-memory.md` — per-file resampling distance, memory ceilings for `phl_admin3`/`idn_admin3`
- `docs/how-to/publishing.md` — PyPI release process (GitHub Release → OIDC trusted publisher)
- `docs/how-to/verify-duckdb-function.md` — DuckDB/spatial function lookup commands
- `docs/adr/` — immutable decision records referenced from Key Patterns above
