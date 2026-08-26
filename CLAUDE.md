# CLAUDE.md

## Project Overview

`topo-tools` is a Python package of DuckDB-powered geospatial topology utilities,
`pip install`-able and importable, mirroring the organization of the sister JS app
at `../topo-tools` (a DuckDB-WASM web app with the same tools). It ships thirteen
tools, all used for improving administrative boundary datasets and matching
sub-national boundaries to national boundaries (import-linter contracts
governing which tool may depend on which are in `docs/reference/shared.md`).
Tools are named `{group}-{verb}`: **edge** (boundary-fitting between layers),
**topo** (single-layer topology defects), and **schema** (column
crosswalking); `dissolve` and `change` stand alone for now. Five are
primitives, each standalone AND reused internally by the composite tools
below them:

- **edge-extend**: extends polygon boundaries outward using Voronoi diagrams, producing a complete coverage layer that fills gaps (coastlines, disputed areas, water bodies).
- **edge-clip**: assigns each child to its parent (always `assign-one`), then clips it to that parent's geometry, one `parent_fid` at a time in its own subprocess; a strict one-children-file/one-parent-file/one-output primitive (`edge-mosaic` owns batching many children files against one shared parent load, see `docs/adr/0080`). See `docs/explanation/edge_clip.md`.
- **edge-stitch**: closes seams in an already-tiled layer with one whole-table `ST_CoverageClean` pass. See `docs/explanation/edge_stitch.md`.
- **topo-detect**: scans a single polygon layer for gap/overlap coverage defects and reports them, without fixing anything. See `docs/explanation/topo_detect.md`.
- **dissolve**: aggregates a polygon layer into a coarser one by grouping on attribute columns and unioning geometry per group, auto-keeping every other column that's constant per group and dropping the rest. See `docs/explanation/dissolve.md`.
- **edge-match**: `assign-one` (default, forcing the whole input file onto one majority-vote parent; opt into per-child `assign-many` via `--multi-parent` for files whose children genuinely scatter across multiple parents, see `docs/adr/0082`) → per-group `edge-extend` (own subprocess) → batched `edge-clip` → `edge-stitch`, fitting a child layer into a coarser parent/clip layer (e.g. admin4 into admin0). The children role MAY span multiple raw files per call, combined via a memory-bounded per-file `inputs`+`assign` loop, groups/clip/stitch/outputs running once over the combined result so cross-file children sharing a parent extend together (`--multi-parent`/`step` rejected outright for a multi-file call, see `docs/adr/0084`). Also accepts an opt-in `--merge` (a plain boolean, plus `--parent-include`/`--parent-exclude`/`--child-include`/`--child-exclude`/`--prefer` narrowing flags, the same design `edge-mosaic` uses), which both groups every child with no parent overlap at all into one orphan group of its own (sentinel `PASSTHROUGH_PARENT_FID`), extending it like any other group and keeping it unclipped in the output (materially weaker safety profile than `edge-mosaic`'s own child passthrough, see `docs/adr/0081`), and gap-fills a parent matched by zero children via the shared `fill_unmatched_parents()` helper, identically to `edge-mosaic` (see `docs/adr/0088`). See `docs/explanation/edge_match.md`.
- **edge-mosaic**: `assign-one` → `edge-clip` → `edge-stitch`, fitting an already-extended child layer (a prior `edge_extend()` output) into a new/different parent/clip layer, skipping Voronoi extension entirely. See `docs/explanation/edge_mosaic.md`.
- **topo-clean**: `topo-detect` → fixes the reported coverage defects (gaps, overlaps) with `ST_CoverageClean`, reporting the fix outcome in the issues file for manual review. See `docs/explanation/topo_clean.md`.
- **change**: compares an old/new polygon layer pair and classifies every unit (unchanged/renamed/modified/relocated/split/merge/complex/created/removed) via spatial overlap and optional code/name identity linking; writes a tabular changelog plus a colored spatial overlay layer. See `docs/explanation/change.md`.
- **schema-map**: maps a source-column → target-schema crosswalk by inferring the admin hierarchy structurally (cardinality/containment, never column names) and classifying code vs. name by value shape, deterministically, no LLM; never renames anything itself. See `docs/explanation/schema_map.md`.
- **schema-refactor**: renames/drops columns per a crosswalk from `schema-map` (likely hand-edited first). See `docs/explanation/schema_refactor.md`.
- **schema-crosswalk**: `schema-map` → `schema-refactor`, in one call, so a user can see mapped values right away and iterate by hand-editing the written crosswalk and re-running `schema-refactor` on it. See `docs/explanation/schema_crosswalk.md`.
- **schema-fill**: cascades each admin-hierarchy column down from its nearest non-NULL shallower level and stamps a new `adm_lvl` column (overridable via `--depth-column`) with each row's real depth, levels derived from a `schema-map` target schema; run against an already-clipped/stitched layer, then `dissolve` each level normally. See `docs/explanation/schema_fill.md`.

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
own `topo_tools/core/{tool}/` package. All stages of one `edge_extend()`/
`edge_match()` call share a single file-backed DuckDB connection; tables are
the IPC mechanism between stages (per-group subprocesses inside `edge-match`
are the one exception, see `docs/explanation/edge_match.md`). Three layers,
each with a specific job (mirroring `geoparquet-io`'s `core`/`api`/`cli`
split):

- `topo_tools/core/{edge_extend,assign,edge_clip,edge_stitch,topo_detect,dissolve,schema_fill,edge_match,edge_mosaic,topo_clean,change}/`:
  stage implementations. `core.edge_match`/`core.edge_mosaic` call
  `core.edge_clip`/`core.edge_stitch` stage functions directly (not through
  their own `api.*()`), the same pattern `core.edge_match` uses to call
  `core.edge_extend`'s stage functions directly, and `core.topo_clean` uses
  to call `core.topo_detect`'s issue-detection stage function directly (see
  `docs/adr/0028`). `core.assign` has no `api.*()`/CLI pipeline of its own,
  so it's called one layer up instead, directly from
  `api.edge_mosaic`/`api.edge_clip`/`api.edge_match`. `core.assign`/
  `core.edge_clip`/`core.edge_stitch`/`core.topo_detect`/`core.dissolve` are
  themselves neutral leaves, alongside `core.constants`/`core.coverage`/
  `core.io`/`core.duckdb_utils`/`core.units`; every tool package may import
  any of these ten, none of them may import back. `core.schema_map` is not
  a neutral leaf but MAY be imported by `core.schema_fill` specifically
  (the target-schema YAML mechanism), never the reverse (see
  `docs/adr/0075`); `schema-fill` does not call `core.dissolve` itself,
  a caller runs `dissolve` separately, once per level, after filling (see
  `docs/explanation/schema_fill.md`).
- `topo_tools/api/{edge_extend,edge_clip,edge_stitch,topo_detect,dissolve,schema_fill,edge_match,edge_mosaic,topo_clean,change}.py`:
  public API functions; each chains its own tool's stages for exactly one
  file (or file pair) per call, except `edge-mosaic`'s and `edge-match`'s
  children roles, which MAY span multiple files (see
  `docs/reference/edge_mosaic.md`, `docs/reference/edge_match.md`).
  `edge-clip` is a strict one-children-file/one-parent-file/one-output
  primitive (see `docs/adr/0080`).
- `topo_tools/cli/main.py`: the click CLI, mapping flags/env vars onto one
  `api.*()` call per invocation, one file (or pair) at a time, except
  `edge-mosaic`'s and `edge-match`'s child arguments (MAY be a glob pattern)
  and their `--input` options (repeatable, comma-splittable), no directory
  batching.

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
paths/arguments/`step` values are in `docs/reference/{tool}.md`. Pure
literals live in `topo_tools/core/{tool}/_constants.py` and
`topo_tools/core/constants.py`.

Tables are named `{name}_{stage}[suffix]`: no suffix means one persistent
table; a letter suffix (`_03a`, `_03b`) means multiple and **all** get a
letter, never one left bare; `_tmp{n}` is dropped before the function
returns, invisible unless `--debug`. Each tool uses its own `name` (e.g.
`{input}_edge_match`) so tools never collide on the same input/`tmp_dir`;
per-tool table names are in `docs/explanation/{tool}.md`.

### Key Patterns

- **DuckDB spatial extension** handles all geometry operations (`ST_*` functions), one file-backed connection per input file (`topo_tools/core/duckdb_utils.py`), returned as a `ProfiledConnection` proxy that logs timing/memory per query when `--debug` is set.
- **DuckDB tables as IPC**: stages read and write named tables on the shared connection; no Parquet between stages.
- **Topology validation** (`check_valid_topology()` in every tool's outputs stage, chaining `check_invalid_edges`/`check_gaps`, backed by `has_invalid_edges`/`has_gaps` in `topo_tools/core/coverage.py`) always unnests MultiPolygons first. No byte-exactness check, see the next bullet.
- **`has_gaps()`/`check_valid_topology()` default `gap_maximum_width` to `SNAP_TOLERANCE` (GEOS's own `CoverageCleaner` parameter name, see `docs/adr/0002`), tolerating a wider gap**: a wider leftover gap may be a real hole in the parent/clip layer's own shape (e.g. Lesotho inside South Africa), a real unfilled-by-design gap, or a real unbatched absence, not a defect, so `edge-match`/`edge-mosaic`/`topo-clean`/`edge-stitch` all rely on this default and report any such gap as a `kind='gap'` row in the issues report instead of raising (see `docs/adr/0035`, `docs/adr/0037`, `docs/adr/0038`, `docs/adr/0039`). `edge-extend` is the one outlier, passing `gap_maximum_width=0` explicitly for its zero-tolerance check: it has no parent/clip layer, so any gap in its own coverage is unambiguously a bug. `topo-clean`/`edge-match`/`edge-mosaic`/`edge-stitch` share one issues-table column schema and skip writing the file entirely when it would be empty (see `docs/adr/0035`, `docs/adr/0036`).
- **Geometry column names**: `geom` in DuckDB tables, `geometry` in final output. `duckdb_memory()` profiling caveats are in `docs/explanation/performance.md`.
- **`core.io.read_and_reproject()` raises `ValueError` on invalid source geometry `ST_MakeValid` can't repair, and on a 0-row read.** A 0-row read is a known DuckDB-spatial-bundled-GDAL gap on some real FileGDBs that a system-installed GDAL reads fine; re-export via `gdal vector convert` to GeoParquet/GPKG first as the workaround (see `docs/adr/0053`).
- **`_05_merge.py` joins against nearby originals via bbox-prefiltered, part-exploded join, never a global `ST_Union_Agg` operand** (`_02_lines.py`'s neighbor-union join and `_03_points.py`'s shared-boundary-zone difference both use whole-fid bboxes instead, not interchangeable with part-exploded). `_03_points.py` raises if its differencing drops a fid entirely, and `_06_outputs.py` raises if the extended geometry no longer covers its original footprint (`SNAP_TOLERANCE`-buffered `ST_Covers`). See `docs/adr/0001`, `docs/adr/0090`.
- **Never call `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` inline inside a JOIN's `ON` clause** — can hang indefinitely on high-vertex-count tables. Precompute bbox columns on the joined table/CTE first, as `_05_merge.py` does (see `docs/adr/0014`).
- **Byte-exact preservation of original polygon vertices is not a goal.** `ST_CoverageClean` may shift any polygon's boundary, including previously-untouched ones (see `docs/explanation/topology.md`).
- **`edge-match` reuses `edge-extend`'s stage functions per-group, each in an isolated subprocess** (GEOS's native heap isn't fully released between files). Two subprocess generations per call: per-group `edge-extend`, then a separate batched `edge-clip` pass (see `docs/adr/0020`, `docs/explanation/edge_match.md`).
- **`edge-mosaic` skips Voronoi extension entirely**, assuming the child layer is already a finished `edge_extend()` output; chains `assign-one` → `edge-clip` → `edge-stitch` directly, no per-group subprocess. `edge-mosaic` also accepts an opt-in `--merge` (a plain boolean, plus `--parent-include`/`--parent-exclude`/`--child-include`/`--child-exclude`/`--prefer` narrowing flags), which both keeps a parent matched by zero children in the output unclipped (using the parent's own geometry, via the shared `fill_unmatched_parents()` helper) and keeps a whole unmatched child file unclipped in the output, coupled with copying named parent columns onto every matched child; `edge-match` performs the identical pair of behaviors (see `docs/adr/0088`); `edge-clip` has no equivalent, since only `edge-mosaic`'s children are guaranteed to already be a complete coverage layer (see `docs/adr/0079`, `docs/adr/0083`, superseding `docs/adr/0078`'s child-orphan passthrough). See `docs/explanation/edge_mosaic.md`. With more than one input file, `edge-mosaic` assigns/clips one children file at a time against a cached parent-tile decomposition (the memory-safe pattern standalone `edge-clip` used before it reverted to a strict 1:1 primitive, see `docs/adr/0079`, `docs/adr/0080`).
- **`core/edge_clip/`'s `_engine.main()` clips one `parent_fid` at a time, each in its own subprocess, boundary adaptively grid-tiled**, uniformly for every caller including `edge-match`; a bad `parent_fid` aborts the whole run. Tile size derives from each parent's own vertex density (small parents skip tiling) (see `docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`).
- **Standalone `edge-clip` never expects `parent_fid` on its input**; it always assigns internally via `assign-one` (`api.edge_clip.clip()` calling `core.assign.load_children`/`load_parent`/`assign_one` directly, no local wrapper) before clipping, no strategy flag. `edge-match`/`edge-mosaic` are unaffected, they call `core.edge_clip._engine.main()` directly with their own already-tagged tables (see `docs/adr/0021`).
- **Standalone `edge-clip` is a strict one-children-file/one-parent-file/one-output primitive**; batching many children files against one shared parent load moved to `edge-mosaic` once it adopted the same memory-safe per-file-loop pattern (see `docs/adr/0080`, superseding `docs/adr/0022`/`docs/adr/0023`/`docs/adr/0024`). Its per-parent-fid subprocess working directory (`core/edge_clip/_engine.py`) is always cleared before use regardless of `--debug`, since two callers can land on the same `parent_fid` and collide on a leftover catalog otherwise (see `docs/adr/0025`).
- **Any manually-declared DuckDB table schema fed by `bbox_columns_sql()` MUST insert `BY NAME`, never positionally.** `bbox_columns_sql()`'s emitted column order (`xmin, xmax, ymin, ymax`) doesn't have to match a hand-written `CREATE TABLE`'s order, and a positional insert won't catch a mismatch, it silently swaps values (see `docs/adr/0026`).
- **`core/assign/`'s `assign-one` (per-file majority vote, forcing every child in a file onto its winner unconditionally once one exists) is the default for both `edge-mosaic` and `edge-match`.** `assign-many` (per-child plurality, dropping a zero-overlap child individually) is an `edge-match`-only opt-in (`--multi-parent`), for files whose children genuinely scatter across multiple parents (e.g. a poorly-digitized admin4 layer). A child forced onto its file's winner with zero individual overlap is not dropped at assign time; it still gets clipped and MAY drop later at clip time if its result is empty, reported as a `kind='clip-empty'` issue row (see `docs/explanation/assign.md`, `docs/adr/0019`, `docs/adr/0082`).
- **`core.topo_clean` depends only on the shared leaf modules and `core.topo_detect`, not `core.edge_extend`.** `topo-clean`'s issue detection was extracted into its own standalone `topo-detect` tool, the same primitive-extraction pattern as `assign`/`edge_clip`/`edge_stitch`; `topo_clean` calls `core.topo_detect`'s stage function directly (see `docs/adr/0028`, `docs/explanation/topo_clean.md`, `docs/explanation/topo_detect.md`).
- **`ST_CoverageClean`'s `gap_maximum_width` has no GEOS-native auto-fill default.** `topo-clean`'s `--gap-width auto` mode computes an explicit width from the widest thin detected gap; `all` mode uses a fixed `GAP_MAXIMUM_WIDTH_ALL_DEG = 360` sentinel (see `docs/adr/0002`).
- **`coverage_clean()` (`core/coverage.py`) must call `ST_CoverageClean` positionally, never via DuckDB's `:=` named-argument syntax.** DuckDB binds named arguments to compiled/extension scalar functions purely by position, silently discarding the name (see `docs/adr/0003`).
- **`edge-stitch`'s `_02_clean` stage calls `coverage_clean_escalating()`, not `coverage_clean()` directly**, widening `snapping_distance` past `SNAP_TOLERANCE` one `SNAP_ESCALATION_STEP` at a time (up to `SNAP_ESCALATION_MAX_STEPS`) only if invalid edges remain after the first pass; every other `coverage_clean()` call site is unaffected (see `docs/adr/0089`, `docs/explanation/edge_stitch.md`).
- **`ST_Distance(GEOMETRY, GEOMETRY)` is unreliable for two disjoint polygons at small separations.** Use `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or `ST_MaximumInscribedCircle` instead (see `docs/adr/0004`).
- **`topo_detect/_02_issues.py`'s per-detection-kind retry falls back to an empty result table (logged) if both attempts fail, rather than leaving the table missing.** Any new call site of `_detect_or_empty` must supply `empty_sql` (see `docs/adr/0005`).
- **`change`'s classification runs in Python (`core/change/_03_classify.py`), not SQL**, feature-count-scaled, not vertex-scaled, unlike `edge-extend`/`topo-clean`'s work. See `docs/explanation/change.md`.
- **`change` always uses exact `ST_Intersection`, never point-sampling**, unlike the sister JS app's WASM-only-bug workaround. See `docs/explanation/change.md`.
- **`topo-clean`'s `--maximum-gap-width`/`--snapping-distance` are decimal degrees, not meters** (`_01` is always EPSG:4326). See `docs/explanation/topo_clean.md`.
- **A read-role file argument MAY be an `http://`/`https://` URL to a `.parquet` file**, resolved via `core.io.resolve_input_path()`/`input_basename()`, never plain `Path()` (which mangles a URL's `//`); output-role arguments always stay local paths (see `docs/adr/0043`).
- **`schema-crosswalk` reuses `schema-map`'s and `schema-refactor`'s stage functions directly rather than re-implementing matching or renaming**, the same primitive-reuse pattern as `topo-clean`/`topo-detect` (`docs/adr/0028`), but split across two independent `name` sub-namespaces (`{name}` for `schema-map`'s tables, `f"{name}_apply"` for `schema-refactor`'s) since both hardcode `"{name}_02"` for different data. The apply namespace's `_01` table is a DuckDB **view** over the already-loaded input, not a copy, per this project's memory-constrained deployment targets; it MUST be dropped before any `DROP TABLE IF EXISTS` targets that name, since DuckDB raises a Catalog Error dropping a view as a table even with `IF EXISTS`. See `docs/explanation/schema_crosswalk.md`.
- **`schema-fill` derives every hierarchy level from a `schema-map` target-schema YAML, never a hardcoded column-naming convention**, matching `name_field` and `code_field` independently by their own prefixes (they need not match), cascades each level's NULL columns down via `COALESCE`, and stamps a depth column (`adm_lvl` by default, overridable via `depth_column`/`--depth-column`) from the *original* (pre-fill) code columns so a caller can tell a genuine leaf-depth row from one only ever filled down; a plain, unmodified `dissolve` call per level then carries that column through automatically via its existing auto-keep-constant-column behavior (see `docs/adr/0075`).

### Supported Formats

Input/output: GeoParquet (`.parquet`), GeoPackage (`.gpkg`), Shapefile (`.shp`), GeoJSON (`.geojson`). Output format matches input format.

## Commands

```bash
# Install dependencies
uv sync

# Run the edge-extend tool (processes exactly one file per call)
uv run topo-tools edge-extend example.geojson
# equivalently: uv run python -m topo_tools edge-extend example.geojson

# Run the edge-match tool (fits a child layer into a parent/clip layer)
uv run topo-tools edge-match children.geojson parents.geojson

# Run the edge-mosaic tool (re-clips an already-extended child layer into a new parent layer)
uv run topo-tools edge-mosaic extended_children.parquet new_parents.geojson

# Run edge-clip/edge-stitch/topo-detect standalone (the primitives edge-match/edge-mosaic/topo-clean chain internally)
uv run topo-tools edge-clip children.parquet parents.geojson
uv run topo-tools edge-stitch tiled.geojson
uv run topo-tools topo-detect example.geojson

# Run the dissolve tool (aggregate a layer into a coarser one by grouping on columns)
uv run topo-tools dissolve admin3.geojson --group-by adm2_pcode,adm1_pcode

# Run the schema-fill tool (fill down admin columns, stamp each row's real depth)
uv run topo-tools schema-fill admin4.geojson

# Run the topo-clean tool (topo-detect, then fix gaps+overlaps, reporting the outcome in the issues file)
uv run topo-tools topo-clean example.geojson

# Run the change tool (compares an old/new polygon layer pair)
uv run topo-tools change old.geojson new.geojson

# Run schema-map/schema-refactor standalone (propose a crosswalk, then apply it separately)
uv run topo-tools schema-map example.geojson
uv run topo-tools schema-refactor example.geojson example_crosswalk.csv

# Run the schema-crosswalk tool (schema-map + schema-refactor in one call)
uv run topo-tools schema-crosswalk example.geojson

# Format and lint
uv run ruff format && uv run ruff check
```

Pre-commit hooks run `uv-sync`, `ruff-format`, and `ruff-check` automatically.

## Test Datasets

| Dataset | Use |
| --- | --- |
| **West Africa cluster** (`sen`/`gmb`/`gnb`/`gin`/`civ`/`gha`/`tgo`/`ben`, portolan `adm2`) | Mutually neighboring countries, used for single-file tool tests (edge-extend/edge-match/topo-clean/change) and edge-mosaic's and edge-match's multi-file combine tests |

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

- `docs/tutorials/{tool}.md`: GDAL-style getting-started examples per tool
- `docs/reference/{tool}.md`: behavior contract per tool (`shared.md` for common settings/gates)
- `docs/explanation/{tool}.md`: stage-by-stage detail for `edge_extend`, `topology`, `assign`, `edge_clip`, `edge_stitch`, `topo_detect`, `dissolve`, `edge_match`, `edge_mosaic`, `topo_clean`, `change`, `schema_map`, `schema_refactor`, `schema_crosswalk`, `schema_fill`; notable: `topology.md` has the SPATIAL_JOIN memory bug, `performance.md` has thread-scaling benchmarks + the RTREE experiment, `voronoi-memory.md` has per-file resampling distance and memory ceilings for `phl_admin3`/`idn_admin3`, `edge_match.md` has the `check_gaps` caveat
- `docs/how-to/`: `publishing.md` (PyPI release via OIDC), `verify-duckdb-function.md` (DuckDB/spatial function lookup), `at-scale-testing.md` (portolan catalog layout, picking a test file/pair)
- `docs/adr/README.md`: how to decide ADR vs. `docs/explanation/` vs. CLAUDE.md's Key Patterns; `docs/adr/` itself holds the decision records
