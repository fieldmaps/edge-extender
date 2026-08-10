# CLAUDE.md

## Project Overview

`topo-tools` is a Python package of DuckDB-powered geospatial topology utilities,
`pip install`-able and importable, mirroring the organization of the sister JS app
at `../topo-tools` (a DuckDB-WASM web app with the same tools). It ships eight
tools, all used for improving administrative boundary datasets and matching
sub-national boundaries to national boundaries (import-linter contracts
governing which tool may depend on which are in `docs/reference/shared.md`).
Four are primitives, each standalone AND reused internally by the composite
tools below them:

- **extend**: extends polygon boundaries outward using Voronoi diagrams, producing a complete coverage layer that fills gaps (coastlines, disputed areas, water bodies).
- **clip**: assigns each child to its parent (always `assign-one`), then clips it to that parent's geometry, one `parent_fid` at a time in its own subprocess; the children role MAY span multiple files sharing one parent load. See `docs/explanation/clip.md`.
- **stitch**: closes seams in an already-tiled layer with one whole-table `ST_CoverageClean` pass. See `docs/explanation/stitch.md`.
- **detect**: scans a single polygon layer for gap/overlap coverage defects and reports them, without fixing anything. See `docs/explanation/detect.md`.
- **match**: `assign-many` → per-group `extend` (own subprocess) → batched `clip` → `stitch`, fitting a child layer into a coarser parent/clip layer (e.g. admin4 into admin0). See `docs/explanation/match.md`.
- **mosaic**: `assign-one` → `clip` → `stitch`, fitting an already-extended child layer (a prior `extend()` output) into a new/different parent/clip layer, skipping Voronoi extension entirely. See `docs/explanation/mosaic.md`.
- **clean**: `detect` → fixes the reported coverage defects (gaps, overlaps) with `ST_CoverageClean`, reporting the fix outcome in the issues file for manual review. See `docs/explanation/clean.md`.
- **change**: compares an old/new polygon layer pair and classifies every unit (unchanged/renamed/modified/relocated/split/merge/complex/created/removed) via spatial overlap and optional code/name identity linking; writes a tabular changelog plus a colored spatial overlay layer. See `docs/explanation/change.md`.

## Deployment Targets

The pipeline targets two memory-constrained environments: **DuckDB-WASM in
the browser** (no disk, JS heap only, and the Python pipeline documents the SQL
approach for eventual JS/TS porting) and **memory-limited containers**
(typically 2–4 GB RAM, no swap; pip-install this package into whatever image
you need, no Dockerfile ships here). Prefer approaches that minimize
intermediate materializations, avoid platform-specific calls (`os.sysconf`,
`/proc`, `subprocess`), and work with small buffer budgets.

## Architecture

Each tool's pipeline is a sequence of stages, each a standalone module in its
own `topo_tools/core/{tool}/` package. All stages of one `extend()`/`match()`
call share a single file-backed DuckDB connection; tables are the IPC
mechanism between stages (per-group subprocesses inside `match` are the one
exception, see `docs/explanation/match.md`). Three layers, each with a specific job
(mirroring `geoparquet-io`'s `core`/`api`/`cli` split):

- `topo_tools/core/{extend,assign,clip,stitch,detect,match,mosaic,clean,change}/`:
  stage implementations. `core.match`/`core.mosaic` call
  `core.assign`/`core.clip`/`core.stitch` stage functions directly (not
  through their own `api.*()`), the same pattern `core.match`/`core.change`
  use to call `core.extend`'s stage functions directly, and `core.clean`
  uses to call `core.detect`'s issue-detection stage function directly
  (see `docs/adr/0028`). `core.assign`/`core.clip`/`core.stitch`/
  `core.detect` are themselves neutral leaves, alongside `core.constants`/
  `core.coverage`/`core.io`/`core.duckdb_utils`/`core.units`; every tool
  package may import any of these nine, none of them may import back.
- `topo_tools/api/{extend,clip,stitch,detect,match,mosaic,clean,change}.py`:
  public API functions; each chains its own tool's stages for exactly one
  file (or file pair) per call, except `mosaic`'s and `clip`'s children
  role, which MAY span multiple files (see `docs/reference/mosaic.md`,
  `docs/reference/clip.md`).
- `topo_tools/cli/main.py`: the click CLI, mapping flags/env vars onto one
  `api.*()` call per invocation, one file (or pair) at a time, except
  `mosaic`'s child argument (MAY be a glob pattern) and both `mosaic`'s and
  `clip`'s `--input` option (repeatable, comma-splittable; `clip` also has
  a matching `--output`), no directory batching.

Import boundaries between these layers, and between tools, are mechanically
enforced by `pyproject.toml`'s import-linter contracts, see
`docs/reference/shared.md` for the MUST/MAY rules.

### Pipeline, Configuration & Table Naming

Each tool's stages are numbered modules in its own `topo_tools/core/{tool}/`
package (`_01_...py`, ...), each with its own docstring; behavior contracts
live in `docs/reference/{tool}.md`, stage-by-stage detail in
`docs/explanation/{tool}.md`.

Settings flow in as plain keyword arguments on each tool's own `api.*()`
function, mapped 1:1 from CLI flags/env vars. There's no module-level `argparse`/env
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
- **DuckDB tables as IPC**: stages read and write named tables on the shared connection; no Parquet between stages.
- **Topology validation** (`check_valid_topology()` in most tools' outputs stage, chaining `check_invalid_edges`/`check_gaps`, backed by `has_invalid_edges`/`has_gaps` in `topo_tools/core/coverage.py`; `stitch` calls `check_invalid_edges` alone, see `docs/adr/0027`) always unnests MultiPolygons first. No byte-exactness check, see the next bullet.
- **`match`/`mosaic` call `check_valid_topology()` with `max_gap_width=SNAP_TOLERANCE`, not the strict default `extend` uses**: a wider leftover gap may be a real hole in the parent/clip layer's own shape (e.g. Lesotho inside South Africa), not a defect, so it's reported as a `kind='gap'` row in the issues report instead of raising. `stitch` gained the same gap-issue reporting (still no hard gate on gaps, see `docs/adr/0027`). `clean`/`match`/`mosaic`/`stitch` now share one issues-table column schema and skip writing the file entirely when it would be empty (see `docs/adr/0035`, `docs/adr/0036`).
- **Geometry column names**: `geom` in DuckDB tables, `geometry` in final output. `duckdb_memory()` profiling caveats are in `docs/explanation/performance.md`.
- **`_05_merge.py` joins against nearby originals via bbox-prefiltered, part-exploded join, never a global `ST_Union_Agg` operand** (`_02_lines.py`'s neighbor-union join uses whole-fid bboxes instead, not interchangeable). See `docs/adr/0001`.
- **Never call `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` inline inside a JOIN's `ON` clause** — can hang indefinitely on high-vertex-count tables. Precompute bbox columns on the joined table/CTE first, as `_05_merge.py` does (see `docs/adr/0014`).
- **Byte-exact preservation of original polygon vertices is not a goal.** `ST_CoverageClean` may shift any polygon's boundary, including previously-untouched ones (see `docs/explanation/topology.md`).
- **`match` reuses `extend`'s stage functions per-group, each in an isolated subprocess** (GEOS's native heap isn't fully released between files). Two subprocess generations per call: per-group `extend`, then a separate batched `clip` pass (see `docs/adr/0020`, `docs/explanation/match.md`).
- **`mosaic` skips Voronoi extension entirely**, assuming the child layer is already a finished `extend()` output; chains `assign-one` → `clip` → `stitch` directly, no per-group subprocess. See `docs/explanation/mosaic.md`.
- **`core/clip/`'s `_engine.main()` clips one `parent_fid` at a time, each in its own subprocess, boundary adaptively grid-tiled**, uniformly for every caller including `match`; a bad `parent_fid` aborts the whole run. Tile size derives from each parent's own vertex density (small parents skip tiling) (see `docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`).
- **Standalone `clip` never expects `parent_fid` on its input**; it always assigns internally via `assign-one` (`api.clip.clip()` calling `core.assign._01_inputs`/`_02_one` directly, no local wrapper) before clipping, no strategy flag. `match`/`mosaic` are unaffected, they call `core.clip._engine.main()` directly with their own already-tagged tables (see `docs/adr/0021`).
- **Standalone `clip`'s children role MAY span multiple files, sharing one parent load**; unlike `mosaic`, each children file still gets its own output (`output_paths` MUST be an explicit equal-length list, no auto-naming), and a call with multiple children files raises before writing anything if any one file's rows are all gone after clipping (see `docs/adr/0022`). Unlike `mosaic`, the multi-file case processes one children file at a time behind that shared parent load (`api.clip._clip_each_file()`), not one combined table: profiling showed combining every children file into one `assign` pass before clipping doesn't fit the memory-constrained deployment targets above at real batch scale. `step` MUST be `None` when multiple children files are given (see `docs/adr/0023`). The parent's grid-tile decomposition (`core.assign._02_one.prepare_parent_tiles()`) is built once before that per-file loop and reused by every iteration via `use_cached_tiles=True`, since it depends only on the parent, never the children, and redoing it per file was a multi-hour regression against a ~9.5 minute combined-call baseline (see `docs/adr/0024`). Its per-parent-fid subprocess working directory (`core/clip/_engine.py`) is always cleared before use regardless of `--debug`, since two children files can land on the same `parent_fid` and collide on a leftover catalog otherwise (see `docs/adr/0025`).
- **Any manually-declared DuckDB table schema fed by `bbox_columns_sql()` MUST insert `BY NAME`, never positionally.** `bbox_columns_sql()`'s emitted column order (`xmin, xmax, ymin, ymax`) doesn't have to match a hand-written `CREATE TABLE`'s order, and a positional insert won't catch a mismatch, it silently swaps values (see `docs/adr/0026`).
- **`core/assign/`'s two strategies are picked by the input's geometry state, not by tool-of-origin**: `assign-many` (per-child plurality) for raw/unextended children, `assign-one` (per-file majority vote) for already-extended/overshoot children. See `docs/explanation/assign.md` and `docs/adr/0019`.
- **`core.clean` depends only on the shared leaf modules and `core.detect`, not `core.extend`.** `clean`'s issue detection was extracted into its own standalone `detect` tool, the same primitive-extraction pattern as `assign`/`clip`/`stitch`; `clean` calls `core.detect`'s stage function directly (see `docs/adr/0028`, `docs/explanation/clean.md`, `docs/explanation/detect.md`).
- **`ST_CoverageClean`'s `gap_maximum_width` has no GEOS-native auto-fill default.** `clean`'s `--gap-width auto` mode computes an explicit width from the widest thin detected gap; `all` mode uses a fixed `GAP_MAXIMUM_WIDTH_ALL_DEG = 360` sentinel (see `docs/adr/0002`).
- **`coverage_clean()` (`core/coverage.py`) must call `ST_CoverageClean` positionally, never via DuckDB's `:=` named-argument syntax.** DuckDB binds named arguments to compiled/extension scalar functions purely by position, silently discarding the name (see `docs/adr/0003`).
- **`ST_Distance(GEOMETRY, GEOMETRY)` is unreliable for two disjoint polygons at small separations.** Use `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or `ST_MaximumInscribedCircle` instead (see `docs/adr/0004`).
- **`detect/_02_issues.py`'s per-detection-kind retry falls back to an empty result table (logged) if both attempts fail, rather than leaving the table missing.** Any new call site of `_detect_or_empty` must supply `empty_sql` (see `docs/adr/0005`).
- **`change`'s classification runs in Python (`core/change/_03_classify.py`), not SQL**, feature-count-scaled, not vertex-scaled, unlike `extend`/`clean`'s work. See `docs/explanation/change.md`.
- **`change` always uses exact `ST_Intersection`, never point-sampling**, unlike the sister JS app's WASM-only-bug workaround. See `docs/explanation/change.md`.
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

# Run clip/stitch/detect standalone (the primitives match/mosaic/clean chain internally)
uv run topo-tools clip children.parquet parents.geojson
uv run topo-tools stitch tiled.geojson
uv run topo-tools detect example.geojson

# Run the clean tool (detect, then fix gaps+overlaps, reporting the outcome in the issues file)
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
| **West Africa cluster** (`sen`/`gmb`/`gnb`/`gin`/`civ`/`gha`/`tgo`/`ben`, portolan `adm2`) | Mutually neighboring countries, used for single-file tool tests (extend/match/clean/change) and mosaic's multi-file combine test |

A full portolan catalog (real, large-scale admin boundary data, multiple
countries and admin levels, some with multiple historical versions) is
available for at-scale/real-data stress testing beyond the cluster above:

- **Local copy**: `/Users/computer/GitHub/OCHA-DAP/hdx-scraper-cod-ab-global/portolan`
- **Live/canonical source**: [source.coop/hdx/cod-ab](https://source.coop/hdx/cod-ab),
  STAC root catalog at `https://data.source.coop/hdx/cod-ab/catalog.json`
  (`id: portolan`; per-country `child` links, e.g. `./chl/catalog.json`)

**HARD RULE: the portolan catalog (local copy or live source) is read-only.**
Never write, modify, move, or delete anything inside
`/Users/computer/GitHub/OCHA-DAP/hdx-scraper-cod-ab-global/portolan`. No
`--output-path`/`--overwrite`, no `--tmp-dir`, no `--debug` exports, nothing.
Only ever read from it. Every output/tmp/debug path for a portolan-sourced
test run must point outside the catalog (e.g. the session scratchpad or
`/tmp`).

See `docs/how-to/at-scale-testing.md` for the STAC layout and how to pick a
file (or an old/new comparison pair, for `change`) from the catalog.

## Reference Docs

- `docs/reference/{tool}.md`: behavior contract per tool (`shared.md` for common settings/gates)
- `docs/explanation/{tool}.md`: stage-by-stage detail for `extend`, `topology`, `assign`, `clip`, `stitch`, `detect`, `match`, `mosaic`, `clean`, `change`; notable: `topology.md` has the SPATIAL_JOIN memory bug, `performance.md` has thread-scaling benchmarks + the RTREE experiment, `voronoi-memory.md` has per-file resampling distance and memory ceilings for `phl_admin3`/`idn_admin3`, `match.md` has the `check_gaps` caveat
- `docs/how-to/`: `publishing.md` (PyPI release via OIDC), `verify-duckdb-function.md` (DuckDB/spatial function lookup), `at-scale-testing.md` (portolan catalog layout, picking a test file/pair)
- `docs/adr/README.md`: how to decide ADR vs. `docs/explanation/` vs. CLAUDE.md's Key Patterns; `docs/adr/` itself holds the decision records
