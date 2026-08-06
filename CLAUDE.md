# CLAUDE.md

## Verification Over Recall

- Never rely on remembered knowledge for libraries, APIs, or frameworks —
  check installed versions and docs before writing code or making claims
- If you lack verified information, acknowledge uncertainty and investigate
  first rather than speculate

## Collaboration Style

- Be objective, not agreeable — act as a partner, not a sycophant
- Push back when you disagree, flag tradeoffs honestly, don't sugarcoat problems
- Keep explanations brief and to the point
- Accuracy over speed
- Code comments: terse, max 1–2 lines, only when the WHY is non-obvious; never restate what the code does

## Project Overview

`topo-tools` is a Python package of DuckDB-powered geospatial topology utilities,
`pip install`-able and importable, mirroring the organization of the sister JS app
at `../topo-tools` (a DuckDB-WASM web app with the same tools). It ships four
tools:

- **extend**: extends polygon boundaries outward using Voronoi diagrams,
  producing a complete coverage layer that fills gaps (e.g., coastlines,
  disputed areas, water bodies).
- **match**: fits a child polygon layer into a coarser parent/clip layer
  (e.g. admin4 into admin0) by assigning each child to the parent it shares
  the largest area with, grouping children by that assignment, running
  `extend`'s pipeline within each group, and clipping each group's result to
  its own parent. `core.match` depends on `core.extend`; the reverse
  dependency is forbidden by an import-linter contract (see Key Patterns).
- **clean**: detects and fixes coverage defects (gaps, overlaps) in a single
  polygon layer with `ST_CoverageClean`, reporting them in a separate issues
  file alongside the cleaned dataset for manual review. Sliver
  detection/reporting was removed (never auto-fixable, and detection itself
  was unreliable even at tiny real-data scale -- see `docs/clean.md`).
  `core.clean` depends only on the shared `core.io`/`core.coverage` leaf
  modules, not on `core.extend`. See `docs/clean.md`.
- **change**: compares two versions of a polygon layer (old vs. new) and
  classifies every unit as unchanged/renamed/modified/relocated/split/merge/
  complex/created/removed, using spatial overlap (`tau_match`/`tau_same`
  thresholds) and, optionally, code/name identity linking; always writes a
  tabular changelog plus a spatial overlay layer colored by relationship
  class. `core.change` depends on `core.extend`; the reverse dependency
  is forbidden by the same kind of import-linter contract as `match`/
  `clean`. See `docs/change.md`.

All four are used for improving administrative boundary datasets and
matching sub-national boundaries to national boundaries.

## Deployment Targets

The pipeline is designed for two memory-constrained environments:

1. **DuckDB-WASM in the browser** — no disk, JavaScript heap only; the Python pipeline logic documents the SQL approach for eventual JS/TS porting
2. **Memory-limited containers** — typically 2–4 GB RAM, no swap; this repo doesn't ship a Dockerfile itself (pip-install this package into whatever container image you need), but the memory model still targets that class of deployment

Memory efficiency is a first-class concern. Prefer approaches that minimize intermediate materializations, avoid platform-specific calls (`os.sysconf`, `/proc`, `subprocess`), and work with small buffer budgets.

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
extended,matched}.parquet`. Distinct `vNN` directories are always genuinely
different content (a new `vNN` is only cut when the boundaries actually
change), and `latest` points to whichever `vNN` is newest — but not every
country has more than one `vNN` yet, so there's no old/new pair to diff
(e.g. Chile only has `v01` so far). Check for multiple `vNN` directories
before picking a country for an old/new comparison; Philippines admin3
`v02`→`v03` is a real diff, used for `change`'s first at-scale test.

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
exception — see `docs/match.md`). Three layers, each with a specific job
(mirroring `geoparquet-io`'s `core`/`api`/`cli` split — see ADRs
`0001-cli-core-separation`/`0004-python-api-mirrors-cli` in that repo):

- `topo_tools/core/extend/`, `topo_tools/core/match/`, `topo_tools/core/clean/`,
  `topo_tools/core/change/` — the real stage implementations. No `click`
  import. `core.match` and `core.change` each import from `core.extend`
  (reusing `extend`'s own Voronoi-pipeline stage functions); the reverse is
  forbidden by import-linter contracts (`pyproject.toml`). All four tools,
  plus `core.duckdb_utils`, may import the neutral shared leaf modules
  `core.constants`/`core.coverage`/`core.io` (generic constants,
  coverage-topology validation/repair, and geodata read/write helpers used
  by more than one tool) — those leaf modules never import back from any
  tool package, also enforced by import-linter.
- `topo_tools/api/extend.py`, `topo_tools/api/match.py`, `topo_tools/api/clean.py`,
  `topo_tools/api/change.py` — the public `extend()`/`match()`/`clean()`/
  `change()` functions; each chains its own tool's stages together for
  exactly one file (or one child file + one clip file, or one old file + one
  new file) per call. No `click` import.
- `topo_tools/cli/main.py` — the click CLI; maps flags/env vars onto a single
  `api.extend()`/`api.match()`/`api.clean()`/`api.change()` call per
  invocation. Processes exactly one file (or file pair) per invocation — no
  directory batching. The only layer allowed to import `click`.

### Pipeline Stages

1. **`inputs.main`** — Reads geodata via DuckDB `ST_Read`, reprojects to EPSG:4326, stores as `*_01` (geometry). Then pre-checks `_01` with `ST_CoverageInvalidEdges_Agg`; if it finds invalid edges, runs `ST_CoverageClean` over the whole table and rewrites `*_01` in place. No-op otherwise. Requires DuckDB spatial ≥ 1.5.3 for native `ST_CoverageClean`. No memory-budget check here — `ST_CoverageClean`'s cost scales with the file's own raw vertex count with no resampling lever to shrink it (`phl_admin3`, 13.85M vertices, needs ~5.9GB and won't fit a 4GB deployment — see `docs/voronoi-memory.md`). Does not distinguish real holes from digitization slivers — inputs are expected to be pre-cleaned upstream; any narrow gap that slips through is treated the same as a real hole and left for `merge.main`'s Voronoi extension to divide. Byte-exact preservation of untouched polygons is not a goal — see Key Patterns.
2. **`lines.main`** — Extracts each polygon's exterior boundary (its own boundary minus a bbox-prefiltered union of its neighbors' boundaries); produces `*_02`. Same caveat as `inputs.main`: the neighbor-union self-join's cost scales with `_01`'s raw vertex count with no resampling lever (`idn_admin3`, 7.48M vertices, needs ~5.4GB — see `docs/voronoi-memory.md`); no runtime memory check here.
3. **`attempt.main`** — Wrapper around `points.main` + `voronoi.main` that retries with doubling distance on failure (0.0002 → 0.1024, up to 10 attempts); `points.main` creates `*_03a` (buffered endpoint union) and `*_03b` (interpolated points), `voronoi.main` generates Voronoi polygons (`*_04`)
4. **`merge.main`** — Unions each fid's original geometry with its Voronoi extension (`*_04`) minus a bbox-prefiltered union of nearby originals, then runs a single whole-table `ST_CoverageClean` pass to close floating-point-scale seams (`*_05`)
5. **`outputs.main`** — Validates topology and exports via DuckDB COPY

### Match Pipeline Stages

1. **`_01_inputs.main`** — Loads and coverage-cleans both the child and
   parent/clip layers by delegating twice to `extend`'s own `_01_inputs.main`
   (`{name}_child_01`, `{name}_parent_01`).
2. **`_02_assign.main`** — Assigns each child to the parent it shares the
   largest area with (bbox-prefiltered, part-exploded, ranked in EPSG:8857);
   drops and logs children with zero overlap with any parent
   (`{name}_02_pairs`, `{name}_02_assign`, `{name}_02_unassigned`).
3. **`_03_groups.main`** — Groups children by assigned parent (always, even a
   group of one); for each group, exports its children + parent geometry to
   Parquet, runs `extend`'s `_02_lines`/`attempt`/`_05_merge` stage functions
   in an isolated `multiprocessing` (`spawn`) subprocess, clips the result to
   that group's parent, appends survivors into `{name}_03`. A failed group is
   logged and dropped, not fatal — `match()` only raises if no group produces
   any output at all. See `docs/match.md` for the full rationale.
4. **`_04_merge.main`** — Single whole-table `ST_CoverageClean` pass over
   `{name}_03` to close cross-group seams (`{name}_04`).
5. **`_05_outputs.main`** — Validates topology (reusing `check_overlaps`/
   `check_gaps` from the shared `core/coverage.py`) and exports via DuckDB
   COPY.

### Clean Pipeline Stages

1. **`_01_inputs.main`** — Reads and reprojects via the shared
   `core.io.read_and_reproject()` helper, **without** `extend`'s own
   auto-clean pre-check — `clean`'s detection stage needs to see the raw,
   uncleaned input (`{name}_01`).
2. **`_02_issues.main`** — Detects gap/overlap defects, writing one issues
   table (`{name}_02`: `key`, `kind`, `area_m2`, `max_width_m`, `unit_a`,
   `unit_b`, `geom` — Polygon geometry). Gaps only catch fully-enclosed
   holes; overlaps are bbox-prefiltered pairwise intersections. See
   `docs/clean.md`.
3. **`_03_clean.main`** — Fixes gaps/overlaps via the shared
   `core.coverage.coverage_clean()` (gated: a no-op copy only if the input
   has no coverage violations *and* no detected gap qualifies to fill under
   the resolved `gap_maximum_width` — `has_coverage_violations()` alone
   can't stand in for "nothing to fix," since it never detects gaps),
   writing `{name}_03`. Retries the resolved `gap_maximum_width` through an
   escalation ladder (widening only, never below the `auto`/`all`/explicit
   target) if the result still has invalid edges, fails a total-area
   sanity floor, has a fid that eroded with no detected defect of its own
   to explain it, or has a fid whose fixed geometry isn't a
   Polygon/MultiPolygon; raises if every rung fails. Logs the accepted
   result's total area change (gained/lost, as a percentage) either way.
   See `docs/clean.md`.
4. **`_04_outputs.main`** — Validates overlaps are gone (`check_overlaps`,
   hard gate); logs (does not raise on) any gaps left unfilled by design;
   extends `{name}_02` with each issue's actual fix outcome (an overlap
   row's two units' own real area change, a gap row's actually-filled
   area) computed from `{name}_01`/`{name}_03`; exports both the cleaned
   dataset and the issues report. Does **not** reuse `check_gaps` as a hard
   gate — unlike `extend`/`match`, `clean` can legitimately leave gaps
   unfilled.

### Change Pipeline Stages

1. **`_01_inputs.main`** — Loads and coverage-cleans both the old and new
   layers by delegating twice to `extend`'s own `_01_inputs.main`
   (`{name}_a_01`, `{name}_b_01`).
2. **`_02_overlap.main`** — Computes `shared_area`/`coverage_a`/`coverage_b`/
   `iou` for every touching `(a_fid, b_fid)` pair (bbox-prefiltered,
   part-exploded, ranked in EPSG:8857, same pattern as match's
   `_02_assign.main`); keeps every pair with `shared_area > 0`, not just a
   top-1 match — classification needs the full pair graph
   (`{name}_02`).
3. **`_03_classify.main`** — Identity (optional, code/name) + spatial
   union-find clustering and cardinality-based classification, run in
   Python (feature-count-scaled, not vertex-scaled — safe to hold in
   memory); writes `{name}_03a` (classified pairs), `{name}_03b` (per-fid
   cluster/class), `{name}_03c` (final changelog table). See
   `docs/change.md` for the identity-claim guard and classification
   rules.
4. **`_04_outputs.main`** — Builds the spatial overlay render layer
   (`{name}_04`: every new-version unit tagged with its relationship_class,
   plus old-version units classed `removed`) and exports both the tabular
   changelog and the overlay layer. No topology hard gate — `change` is a
   read-only comparison, not a fix.

### Configuration

No module-level `argparse`/env parsing anywhere — that pattern used to live in
`app/config.py` and broke `import topo_tools` (parsing the host process's `sys.argv`
as a side effect of importing). Settings now flow in two ways:

- **User-configurable, varies per call** — plain keyword arguments on
  `topo_tools.api.extend.extend()`, threaded explicitly into exactly the stage
  functions that read them (confirmed by reading every stage: `_01_inputs`/`_02_lines`
  need nothing; `_03_points`/`_04_voronoi`/`_05_merge`/`attempt` need `debug`;
  `_06_outputs` needs `debug`; `get_connection` needs `threads` + `debug`).
  `topo_tools/cli/main.py`'s `extend` command maps CLI args/flags/env vars
  1:1 onto these kwargs (env var names match the old `config.py` ones —
  `INPUT_FILE`, `DEBUG`, etc. — via click's `envvar=`; `INPUT_FILE`/
  `OUTPUT_FILE` are positional `click.argument`s, everything else is a
  `click.option`).
- **Not user-configurable, pure literals** — `topo_tools/core/extend/_constants.py`
  (`MAX_POINTS`, `DEFAULT_DISTANCE`, `MAX_POINTS_PER_SEGMENT`, Voronoi-specific)
  and the shared `topo_tools/core/constants.py` (`SNAP_TOLERANCE`,
  `EQUAL_AREA_CRS`, `RESERVED_COLUMN_NAMES`, `COPY_OPTS`, used by more than
  one tool). Safe to import at module load — no argparse, no env reads.

| Setting                    | Description                                                         |
| -------------------------- | ------------------------------------------------------------------- |
| `input_path` / `output_path` | Input/output file paths (one file per call); `output_path` defaults to `input_path` with an `_extended` suffix when omitted |
| `tmp_dir`                  | Intermediate DuckDB + Parquet location; defaults to a fresh `tempfile.mkdtemp()` when unset, cleaned up after the call unless `debug` |
| `threads`                  | DuckDB thread count; unset defers to DuckDB default                 |
| `overwrite`                | Overwrite existing output                                           |
| `debug`                    | Keep intermediate tables, export all to Parquet, and log timing + memory delta per query |
| `step`                     | Run only one named stage (inputs/lines/attempt/merge/outputs)       |

`topo_tools.api.match.match()` takes the same settings plus a required
`clip_path` (the parent/clip layer, positional between `input_path` and
`output_path`); `output_path` defaults to an `_matched` suffix instead of
`_extended`, and `step` chooses among `inputs/assign/groups/merge/outputs`.

`topo_tools.api.clean.clean()` takes `input_path`, optional `output_path`
(`_cleaned` suffix) and optional `issues_path` (`_issues` suffix, derived
from `output_path`'s stem), plus `maximum_gap_width` (`"auto"`/`"all"`/a
decimal-degrees string, default `"auto"`), `snapping_distance` (`"auto"`/a
decimal-degrees string, default `"auto"`), and the same
`threads`/`tmp_dir`/`overwrite`/`debug` settings; `step` chooses among
`inputs/issues/clean/outputs`.

`topo_tools.api.change.change()` takes `old_path`/`new_path`
(positional), optional `output_path` (tabular changelog, `.csv`/`.parquet`
only, `"_changelog"` suffix combining both stems if omitted) and optional
`overlay_path` (spatial layer, any of `extend`'s 4 formats, `"_overlay"`
suffix inheriting `old_path`'s format if omitted), plus `tau_match` (default
`0.8`), `tau_same` (default `0.98`), `link_by_code`/`link_by_name` (both
`False` by default), `link_mode` (`"either"`/`"both"`, default `"either"`),
`code_column_a`/`code_column_b`/`name_column_a`/`name_column_b` (auto-detected
via regex when the corresponding link flag is set and no explicit column is
given), and the same `threads`/`tmp_dir`/`overwrite`/`debug` settings; `step`
chooses among `inputs/overlap/classify/outputs`.

### Table Naming Convention

Tables are named `{name}_{stage}[suffix]` where stage is a two-digit number and suffix is either empty, a letter, or `_tmp{n}`:

- **No suffix** — stage produces exactly one persistent table (e.g. `_01`, `_04`, `_05`)
- **Letter suffix (`_03a`, `_03b`)** — stage produces multiple persistent tables; **all** of them get a letter, including the first. Never leave one bare while siblings have letters.
- **`_tmp{n}` suffix** — table is dropped within the same file before the function returns; not visible to downstream stages unless `--debug` is set

The current sequence: `_01` → `_02` → `_03a/_03b` → `_04` → `_05`. `inputs.main`'s coverage-clean pass rewrites `_01` in place when violations are detected; it does not introduce a new suffix.

`match` uses its own `name` (`{input}_match`, distinct from `extend`'s
`{input}` so the two tools' tables/files never collide when run against the
same input path and `tmp_dir`) and its own numbering: `{name}_child_01` /
`{name}_parent_01` → `{name}_02_pairs`/`{name}_02_assign`/`{name}_02_unassigned`
→ `{name}_03` (reassembled groups) → `{name}_04` (final coverage-clean). Each
group's own `extend`-pipeline tables (`group_01` … `group_05`, `group_clip`)
live in a private, per-group DuckDB file (`group.duckdb`, one at a time,
reused sequentially) inside `{tmp_dir}/{name}_g{parent_fid}/`, never in
`match`'s own connection — see `docs/match.md`.

`clean` uses its own `name` (`{input}_clean`, distinct from `extend`/`match`
for the same collision-avoidance reason) and its own numbering: `{name}_01`
→ `{name}_02` (with `_02_tmp1`/`_02_tmp2`/`_02_tmp3` per-kind intermediates,
dropped unless `--debug`) → `{name}_03` (post-`ST_CoverageClean`). No `_04`
whole-table re-clean pass like `extend`/`match` have — `clean` operates on
one table throughout, there's no per-group reassembly seam to close.

`change` uses its own `name` (`{old_input}_changelog`, distinct from
`extend`/`match`/`clean` for the same collision-avoidance reason) and its
own numbering: `{name}_a_01`/`{name}_b_01` (old/new, mirroring match's
`_child_01`/`_parent_01`) → `{name}_02` (overlap pairs, with
`_02_tmp1`..`_02_tmp5` intermediates, dropped unless `--debug`) →
`{name}_03a`/`{name}_03b`/`{name}_03c` (classified pairs, per-fid class,
final changelog table — three persistent outputs, all lettered per
convention) → `{name}_04` (spatial overlay render). No whole-table re-clean
pass — `change` is a read-only comparison, not a fix.

### Key Patterns

- **DuckDB spatial extension** handles all geometry operations (`ST_*` functions). One file-backed connection is created per input file in `topo_tools/core/duckdb_utils.py` and returned as a `ProfiledConnection` proxy that logs timing and memory per query when `--debug` is set.
- **DuckDB tables as IPC** — stages read and write named tables on the shared connection; no Parquet between stages.
- **Topology validation** in `_06_outputs.py` (`_check_overlaps`, `_check_gaps`) always runs in outputs, backed by `has_coverage_violations` in the shared `topo_tools/core/coverage.py`. Both unnest MultiPolygon geometries before checking to ensure correct coverage validation across individual polygon pieces. There is no byte-exactness check — see below.
- **`core/constants.py`, `core/coverage.py`, `core/io.py` are neutral leaf modules, alongside `core/duckdb_utils.py`.** Any of the four tools (or a future one) may import them; none of the four may import back from `core.extend`/`match`/`clean`/`change`, enforced by a `*-is-leaf` import-linter contract per module. A generic constant/helper used by 2+ tools belongs here, not in any one tool's own `_constants.py` or duplicated across tools.
- **Geometry column names**: `geom` in DuckDB tables, `geometry` in final output.
- **`duckdb_memory()` measurements in isolation underestimate pipeline peaks.** A fresh connection with few tables in the DuckDB file can show 4 GB for a query that peaks at 8 GB in a full pipeline run, because the buffer pool from other large tables (`_01`, `_04`, `_05_tmp1`, etc.) adds several GB of additional pressure. Profile with `--step=X --debug` on a database file that already has all prior-stage tables present.
- **Avoid materializing one global `ST_Union_Agg` of `_01` as a per-row `ST_Difference`/join operand.** At Chile scale the union can hold millions of vertices; using it as an operand against every fid individually made GEOS pay that cost on every row and OOM'd outright (confirmed during development of `_05_merge.py`). Use a bbox-prefiltered join against nearby originals instead (see `_05_merge.py`'s `_05_tmp1`/`_05_tmp2`, which explodes multipolygon fids into parts first — a whole-fid bbox can span mainland-to-remote-island and defeat the prefilter). **`_02_lines.py`'s neighbor-union self-join deliberately does NOT do this** — it joins on whole-fid bboxes. Exploding it into per-part bboxes looks like the same fix but isn't: it helps files with many fids that each have a few widely-scattered parts (e.g. `idn_admin3`) but badly regresses files with one fid made of thousands of tightly-clustered parts (e.g. `chl_admin3` has a single fid with 3,796 parts) by multiplying self-join row count far more than the tighter bboxes save — confirmed empirically (Chile: 3.3GB peak with whole-fid bboxes vs. OOM at 10GB+ with per-part bboxes). See `docs/voronoi-memory.md`.
- **Byte-exact preservation of original polygon vertices is not a goal.** `ST_CoverageClean` may shift any polygon's boundary, including previously-untouched ones. Don't reintroduce per-fid violator scoping, snapshot/restore, or escalation logic to protect vertex-level exactness — that machinery was removed deliberately (see `docs/topology.md`).
- **`core.match` may import from `core.extend`; the reverse is forbidden.** Enforced by the `match-may-use-extend-not-reverse` import-linter contract in `pyproject.toml`. `match` reuses `extend`'s stage functions per-group rather than duplicating Voronoi gap-filling logic; `extend` must stay usable standalone with zero knowledge of `match`.
- **`match`'s per-group work runs in an isolated subprocess, not `match()`'s own connection/process.** GEOS's native heap isn't fully released between files even after closing the DuckDB connection (the same finding that makes `extend()` process one file per OS process) — a many-parent-group `match()` run would hit the same failure mode in-process, just with groups substituting for files. See `docs/match.md`.
- **`core.clean` depends only on the shared leaf modules, not on `core.extend`.** `clean` reuses `core.io.read_and_reproject()` (inputs, without extend's own auto-clean pre-check) and `core.coverage.coverage_clean()` (fix stage) — both neutral, tool-independent helpers, not `extend`-specific code.
- **`ST_CoverageClean`'s `gap_maximum_width` has no GEOS-native auto-fill default.** Verified against upstream source (duckdb-spatial's `geos_module.cpp`, GEOS's `CoverageCleaner.h`/`.cpp`): the C++ class member is hardcoded to `0.0`, and a negative/omitted value is a no-op that leaves it there — unlike `snapping_distance`, which does have a real computed auto-default (`extent_diameter / 1e8`). `clean`'s `--gap-width auto` mode computes an explicit width from the widest *thin* detected gap; `all` mode computes one from the widest gap overall (thin or not) — both avoid relying on any GEOS-side "auto-fill." A fixed "just make it huge" constant for `all` was tried and rejected — see the next bullet. See `docs/clean.md`.
- **`ST_CoverageClean` has two confirmed real failure modes tied to `gap_maximum_width`, independent of `snapping_distance` (confirmed: sweeping `snapping_distance` alone across 8 orders of magnitude never fixed either one).** (1) Residual invalid edges, or an outright `TopologyException`, at specific widths — verified against a real admin-boundary defect via a controlled experiment holding every input fixed and varying only `gap_maximum_width`: a ~0.25% change deterministically flipped an unrelated part of the coverage between valid/invalid, 3/3 reproducible each way (this was initially misdiagnosed as GEOS nondeterminism before controlling for a concurrent code change — it is fully deterministic given fixed inputs). Mapping the surrounding width-space at 1.1m and then 1cm resolution showed the bad region is patchy, not a single band — good/bad/good/**crash**/bad/good across a ~24m span. (2) Silent area erosion once the width approaches the scale of the data's own local topology — confirmed on real data at multi-degree widths (164-fid layer, 190km² → 50km² at 10°, fully empty at 20°+, which is why `all` mode computes its width from actually-detected gaps rather than using any large fixed constant) **and**, more surprisingly, on a small synthetic fixture at a width matching one of its own real gaps exactly, but only when combined with a second, differently-scaled group in the same `ST_CoverageClean` call — several unrelated polygons collapsed to zero area even though each group was fine processed alone. That second trigger condition isn't fully understood and is worth a closer look or an upstream bug report. `_03_clean.py`'s `main()` handles both failure modes with `GAP_WIDTH_ESCALATION_FACTORS`, a validated escalation ladder (only ever widens the resolved target, never narrows it, preserving `auto`/`all`/explicit semantics) that checks `has_coverage_violations()`, a total-area sanity floor (`AREA_SANITY_FACTOR = 0.8`) — the invalid-edges check alone passes a totally empty result as "no violations," confirmed directly, so it cannot catch failure mode 2 on its own — a per-fid erosion check, and a geometry-type check. The total-area floor alone still misses a *small* feature collapsing entirely inside a much larger dataset, so each fid is also checked individually: a fid touching a gap that gets filled or party to a detected overlap is exempt (confirmed directly that gap-filling can legitimately reassign an adjacent, overlap-uninvolved fid's entire area into a neighbor — two small connector strips bordering a filled sliver gap were fully absorbed into a third fid in testing), but any other fid is expected to come out essentially unchanged, and any fid whose fixed geometry isn't a Polygon/MultiPolygon fails outright (`ST_Area()` on a mixed `GEOMETRYCOLLECTION` silently sums only the polygonal parts, so a fid partly reduced to a stray line could otherwise pass as area-preserving). Neither check uses a guessed percentage floor — full containment (one fid entirely absorbed by another) and gap-neighborhood redistribution are both legitimate 100%-loss outcomes for the fid actually involved, which a flat percentage would incorrectly reject. Raises a clear error if every rung fails rather than silently degrading to a different gap-filling behavior; logs the accepted result's total area change either way. Validated end-to-end on the real stress-case dataset in both `auto` and `all` modes: output area matches input to within ~0.0003km² out of ~190km². See `docs/clean.md`.
- **`ST_Distance(GEOMETRY, GEOMETRY)` is unreliable for two disjoint polygons at small separations** — confirmed it returns `0.0` for two clearly-separated polygons (~3cm apart) on the installed DuckDB version, while the equivalent POINT/LINESTRING pair correctly returns the true distance. Use `ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or `ST_MaximumInscribedCircle` instead when checking polygon disjointness/gap width.
- **`clean/_02_issues.py`'s per-detection-kind retry didn't actually fall back to empty on a double failure.** The module docstring always promised "retried once at reduced precision, then falls back to an empty result (logged) rather than raising," but `_run_with_retry` only logged on the second failure — it never created the temp table, so a double failure left it entirely missing and crashed `main()`'s downstream `UNION ALL` with a binder/catalog error instead of degrading gracefully. Fixed by passing each call site an explicit `empty_sql` that `_run_with_retry` executes when both attempts fail, so the target table always exists afterward. Same "one kind failing shouldn't block the others" contract as before, now actually honored.
- **`core.change` may import from `core.extend`; the reverse is forbidden.** Enforced by the `change-may-use-extend-not-reverse` import-linter contract. `change` reuses `extend`'s `_01_inputs.main()` (both layers pre-cleaned) plus the shared `core.constants.COPY_OPTS` (overlay export) and `core.constants.EQUAL_AREA_CRS`; it deliberately does **not** import from `core.match` even though `_02_overlap.py`'s bbox-prefiltered join mirrors `_02_assign.py`'s pattern closely — `change` stays decoupled from `match`/`clean` the same way they're decoupled from each other.
- **`EQUAL_AREA_CRS` ("EPSG:8857") and `SNAP_TOLERANCE` live in the shared `core/constants.py`, not in any one tool's own `_constants.py`.** `match`, `clean`, and `change` all need one or both; none should depend on another's private constants module. `match`/`change` still don't depend on each other.
- **`change`'s classification runs in Python, not SQL.** Union-find and cardinality classification (`core/change/_03_classify.py`, ported from topo-tools-js's `classify.ts`) scale with feature count, not vertex count, so fetching every pair row into memory and classifying with plain Python dicts/sets is safe under this repo's memory model even for a large admin layer — unlike the vertex-scaled Voronoi/coverage-clean work `extend`/`clean` do. See `docs/change.md`.
- **`change` always uses exact `ST_Intersection`, never point-sampling.** The sister JS app falls back to a 32×32 point-sampling overlap estimate on a documented WASM-only GEOS OverlayNG bug; JS's own git history confirmed the bug doesn't reproduce natively, so the Python port drops the fallback entirely rather than porting dead-weight WASM-workaround code. See `docs/change.md`.
- **`clean`'s `--maximum-gap-width`/`--snapping-distance` are decimal degrees, not meters.** `_01` is always EPSG:4326, so `ST_CoverageClean` itself takes these in degrees; a meters-based CLI would need a dataset-wide `cos(centroid latitude)` conversion (as `--maximum-gap-width`'s old meters mode did) that's a real approximation over large north-south extents and adds indirection between what a user types and what GEOS receives. `core/clean/_units.py` now only converts the other direction (degrees/m² → meters/m² for the issues file's `area_m2`/`max_width_m` reporting columns); it no longer converts any CLI input. `clean` applies no floating-point noise floor to detected gaps/overlaps -- empirical testing found no native GEOS jitter to guard against. See `docs/clean.md`.

### Supported Formats

Input/output: GeoParquet (`.parquet`), GeoPackage (`.gpkg`), Shapefile (`.shp`), GeoJSON (`.geojson`). Output format matches input format.

## DuckDB Function Verification

Do not rely on recalled knowledge about DuckDB or spatial extension functions — verify against the installed version before making claims or writing code. See the `verify-duckdb-function` skill for the lookup commands (CLI + `gh api`).

## Reference Docs

- `docs/topology.md` — topology approach (ST_Node + ST_Polygonize), DuckDB spatial function reference, SPATIAL_JOIN memory reservation bug
- `docs/match.md` — match's largest-overlap assignment algorithm, per-group subprocess isolation rationale, the `fids=None` whole-table-clean constraint, and the check_gaps/parent-layer-gaps caveat
- `docs/clean.md` — clean's gap/overlap detection approach, why sliver detection/reporting was removed, verified `ST_CoverageClean` parameter semantics (`gap_maximum_width` has no GEOS-native auto-fill default, unlike `snapping_distance`), and the issues-file schema
- `docs/change.md` — change's overlap/classification algorithm, why the WASM point-sampling fallback is dropped, the identity-claim guard's purpose, the output schema, and the two-output-file design
- `docs/performance.md` — thread-scaling benchmarks, pipeline phase profiles, `get_connection` settings, RTREE experiment
- `docs/voronoi-memory.md` — Voronoi collinearity degeneracy fix (segment cap, dynamic resampling distance), why the `--memory-gb`-derived point budget that once sized it was tried and then removed, and two documented (not gated) memory ceilings in `inputs.py`/`lines.py` that genuinely exceed 4GB for large files (`phl_admin3`, `idn_admin3`)
- `docs/publishing.md` — PyPI release process (GitHub Release → required-reviewer approval → trusted-publisher OIDC), and the TestPyPI rehearsal loop for testing packaging changes
