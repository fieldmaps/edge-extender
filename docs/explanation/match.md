# Matching Reference

`match` fits a **child** polygon layer into a coarser **parent**/clip layer
(e.g. admin4 into admin0), reusing `extend`'s Voronoi gap-filling pipeline
under the hood, then the same `assign`/`clip`/`stitch` primitives `mosaic`
uses. This doc covers the parts that are specific to `match`: the
overlap/assignment algorithm, the per-group subprocess design, and the
constraints it inherits from `extend`. See `docs/explanation/topology.md` for the
coverage-clean/`SPATIAL_JOIN` background both tools share.

## Usage

```sh
topo-tools match children.geojson parents.geojson
```

```python
from topo_tools import match

match("admin4.geojson", "admin0.geojson", "admin4_matched.geojson")
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_matched` suffix.

| Option | Description |
| --- | --- |
| `--overwrite` | Overwrite an existing output file. |
| `--threads` | DuckDB thread count. |
| `--debug` | Keep intermediate tables, export to Parquet, log timing/memory per query. |
| `--tmp-dir` | Intermediate DuckDB + Parquet location. |
| `--step` | Run only one named stage: `inputs`, `assign`, `groups`, `clip`, `stitch`, `outputs`. |

```sh
# Fit an admin4 layer into a single country boundary
topo-tools match adm4.geojson adm0.geojson

# Fit admin3 into admin2 groups, each cleaned against its own parent
topo-tools match adm3.gpkg adm2.gpkg adm3_matched.gpkg
```

Each parent's group of children runs in its own isolated subprocess, so a run
with many parents (e.g. matching a nationwide admin4 layer against dozens of
admin2 units) scales without one large group's memory use affecting another's.

Run `topo-tools match --help` for the full, always-current option list.

## Pipeline

1. **`_01_inputs`**: loads and coverage-cleans both layers by delegating
   twice to `extend`'s own loader (`{name}_child_01`, `{name}_parent_01`).
2. **assign**: calls `core.assign._02_many.main()` directly: assigns each
   child to the parent it shares the largest area with (plurality, not
   majority); drops and logs children with zero overlap with any parent,
   keeping their geometry for the issues report. See
   `docs/explanation/assign.md` for the algorithm.
3. **`_02_groups`**: groups children by their assigned parent (always, even
   a group of exactly one parent), runs `extend`'s pipeline within each group
   in an isolated subprocess, then reassembles the survivors, tagging each
   row with its group's own `parent_fid`. No clipping happens here anymore
   (see "Two subprocess generations" below). A failed group's children are
   recorded, with the parent id and failure reason, for the issues report.
4. **`_03_clip`**: one batched call into `core.clip.main()` over the whole
   reassembled table at once, clipping every row to its own `parent_fid`'s
   geometry. See `docs/explanation/clip.md` for the algorithm.
5. **`_04_stitch`**: calls `core.stitch._02_clean.main()` directly: a
   single whole-table `ST_CoverageClean` pass over the clipped output to
   close cross-group seams. See `docs/explanation/stitch.md`.
6. **`_05_outputs`**: validates topology (any overlap, or a gap at or below
   `SNAP_TOLERANCE`, raises), builds the issues report from the dropped
   children collected in stages 2/3 plus any leftover gap wider than
   `SNAP_TOLERANCE`, logs a warning if any such gap remains, and exports
   both the final layer and the issues report (only when it has rows).

## Two subprocess generations: extend, then batched clip

Before the `assign`/`clip`/`stitch` extraction, each group's subprocess ran
`extend`'s pipeline *and* clipped to that group's parent in the same
process. `core.clip` now always isolates per distinct `parent_fid` in its
own spawned subprocess, uniformly for every caller, so `match` moved to two
subprocess generations per run instead: a per-group `extend`-only
subprocess (unchanged in count/shape from before), followed by a second,
later generation of per-`parent_fid` clip subprocesses (`clip`'s own
mechanism, batched over the whole reassembled table). See
`docs/adr/0020-match-clip-two-subprocess-generations.md` for the empirical
re-verification this required and its results.

One consequence: a single bad `parent_fid` in the `clip` step now aborts
the whole run, rather than match's old per-group continue-past-failure
behavior for clip failures specifically. Per-group `extend` failures (OOM,
or exhausting `attempt.py`'s 10 retries) still continue, dropping just that
group, as before; only clip's own hard-fail-on-first-bad-`parent_fid`
semantics are new, and apply uniformly to every `clip` caller including
`match` (see `docs/explanation/clip.md`).

## Per-group subprocess isolation (extend)

Each group's `extend` pipeline (`_02_lines` → `attempt` → `_05_merge`) runs in
its own fresh `multiprocessing` (`spawn` context) subprocess, not the parent
`match()` call's shared connection. This is a deliberate design choice, not
an afterthought: CLAUDE.md documents a real, previously-confirmed finding
that GEOS's native heap isn't fully released between files even after
closing the DuckDB connection, which is exactly why `extend()` processes one
file per OS process today. A many-parent-group `match()` run (e.g.
admin4-into-admin2 for a country with dozens or hundreds of admin2 units)
would hit the identical failure mode in-process, just with groups
substituting for files, if groups shared one process. Building the same
per-file-per-process isolation guarantee down to group granularity avoids
that outright rather than hoping in-process cleanup is sufficient.

Data crosses the process boundary as small Parquet files (`child.parquet`,
`parent.parquet` in, `output.parquet` out), never a shared connection: a
DuckDB file is single-writer, and the group's own DuckDB file
(`group.duckdb`) lives entirely inside that group's private temp directory,
discarded when the group finishes (unless `--debug`). Verified empirically
that a `GEOMETRY` column round-trips correctly through
`COPY ... TO (FORMAT PARQUET)` + `read_parquet(...)` in the installed DuckDB
version; no `GEOPARQUET_VERSION` option is needed for this internal,
DuckDB-to-DuckDB round trip.

`match()` raises only if **no** group produced any output at all (see
"Two subprocess generations" above for the separate, stricter clip-stage
failure behavior).

A freshly-spawned process has no logging configuration of its own
(`basicConfig` only ever runs in `cli/main.py`, in the parent process); the
worker puts a success/error signal on a `multiprocessing.Queue` instead of
relying solely on its own log output, and only configures logging locally
(mirroring `cli/main.py`'s own call, teed to a per-group log file) when
`--debug` is set, so `ProfiledConnection`'s per-query timing/RSS output isn't
silently dropped during a debug run.

**Real-world smoke test**: `bdi_admin4.gpkg` (3,067 features) matched against
`bdi_admin2.parquet` (119 parents) completed successfully end-to-end: 119
subprocess spawns, zero dropped children, zero failed groups, valid output
coverage (see verification steps in the project's implementation history).

**Colombia-scale profiling** (portolan `col/latest/adm3` → `col/latest/adm2`,
`--debug`, Apple Silicon/10 logical cores): 31,880 children against 1,122
parents, 1,120 of them with at least one assigned child (the other 2 parents
had zero overlapping children (not a failure, no adm3 unit fell inside
them). All 1,120 groups and all 1,120 clip subprocesses succeeded: zero
dropped children, zero failed groups. Wall time 38m23s, peak RSS 7.23 GB
(see `docs/adr/0020` for the full before/after comparison against the
pre-extraction fused-subprocess design). Stage breakdown:

| Stage    | Wall time | Share |
| -------- | --------- | ----- |
| inputs   | 59s       | 3%    |
| assign   | 10s       | 0%    |
| groups   | 29m24s    | 77%   |
| clip     | 5m13s     | 14%   |
| stitch   | 46s       | 2%    |
| outputs  | 1m51s     | 4%    |

`groups` still dominates as expected (1,120 sequential subprocess spawns,
each running the per-group `extend` pipeline) but no longer accounts for
the clip work it used to do inline; that now shows up as its own `clip`
stage, batched over all 1,120 parent fids after every group has finished.

## Rejected: `ST_Snap` around the clip step's `ST_Intersection`

`_05_merge.py` snapping the Voronoi cell onto its neighbor union before
`ST_Difference` (see `docs/explanation/topology.md`) measurably reduces how many
untouched fids the final whole-table `ST_CoverageClean` pass has to touch,
because many *independent* per-fid `ST_Difference` calls against
*independently computed* neighbor unions invent slightly different
floating-point crossing points for what should be the same vertex. Two
variants of the same idea were tried in what was then `match`'s own inline
clip step (now `core.clip`), on the theory that a shared, exact parent
boundary (parent layer is itself coverage-cleaned in `_01_inputs.py`, so two
adjacent parents' shared edge is vertex-identical) should let two
independently-clipped groups tile seamlessly if their output vertices land
on that same exact reference:

1. Snap each group's pre-clip geometry onto the parent's vertices, *before*
   `ST_Intersection(t.geom, p.geom)`.
2. Snap the clipped *result* onto the parent's vertices, *after* the
   intersection: the mirror image, covering the case where `ST_Intersection`
   itself perturbs the parent's inherited edge vertices during overlay
   processing rather than `t.geom`'s own vertices being the problem.

Tested both on Burundi, Sri Lanka, Malawi, Senegal, Haiti, Guatemala, and
Chile (admin2-into-admin1 for the first six, admin3-into-admin2 for Chile):
**zero measurable difference**, either direction, on every metric checked
(pre-clean invalid-edge flag, count of fids the clean pass actually
touches, whole-table clean peak RSS, wall time): identical or noise-level
(<10%, no consistent direction) on all seven files, including Chile's
56-group stress test (213/213 fids touched both ways, ~2550 MB peak all
three variants).

Root cause, found by extracting the actual invalid-edge geometries on
Burundi (`ST_CoverageInvalidEdges_Agg`, unnested, joined back to nearby
fids): all 171 invalid edges border exactly the fid pairs the assign step
places in two *different* parent groups, confirming these are genuinely
cross-group seams, but their lengths run from slivers up to **0.0058°
(~645 m)**, averaging **~12 m**. `SNAP_TOLERANCE` is `1e-8°` (~1.1 mm),
five to six orders of magnitude smaller. This isn't the same failure mode
as `_05_merge.py` at all: it's not two computations of the same crossing
point disagreeing by float noise, it's two *different* groups' Voronoi
extensions, built independently, with no knowledge of each other,
genuinely disagreeing about how far to reach near their shared parent
border. No vertex-snapping tolerance in a sane range closes a
meters-to-hundreds-of-meters gap; that's real gap-filling work, which is
exactly what `stitch`'s whole-table `ST_CoverageClean` pass is for (see
`docs/explanation/stitch.md`). Reverted both variants; the clip step stays
a plain `ST_Intersection`.

## `check_valid_topology` and parent-layer gaps

`_05_outputs.py` calls `check_valid_topology(conn, f"{name}_05")`, relying
on its default `gap_maximum_width=SNAP_TOLERANCE` (see `docs/adr/0039`): it
still raises on any overlap or mismatched edge, but only raises on a gap
at or below `SNAP_TOLERANCE`, not any gap.

A zero-tolerance gate here breaks on a real case: matching South Africa's
admin4 into South Africa's own admin0 boundary correctly reproduces the
interior hole for Lesotho, a country fully enclosed by South Africa's
territory. That hole isn't a defect `match` introduced, it's the parent
layer's own legitimate shape, and the old strict gate raised
`RuntimeError` over it. `match` has no way to distinguish that case from
an actual coverage defect by size alone (both can be wide), so instead of
guessing, it stops treating "wide gap" as fatal and reports it: any gap
wider than `SNAP_TOLERANCE` gets a `kind='gap'` row in the issues report
(width, area, thinness ratio) and a warning log, for a human to review.
Only a leftover gap at or below `SNAP_TOLERANCE` still raises, since
nothing that small should ever survive the pipeline's own noise-floor
cleaning passes; a leftover one there is unambiguously a bug, not a real
absence. See `docs/adr/0035`.

## Debug tables

`--step=groups --debug` exports everything currently in the connection
(`{name}_child_01`, `{name}_parent_01`, `{name}_02_pairs`, `{name}_02_assign`,
`{name}_02_unassigned`, `{name}_03a`, `{name}_03b`), the same as a full run:
group ids
aren't known ahead of time, so there's no static table list to filter to for
that step. Per-group internal detail (the group's own `group.duckdb`,
`group.log`, `child.parquet`, `parent.parquet`, `output.parquet`) is
preserved under `{tmp_dir}/{name}_g{parent_fid}/` when `--debug` is set,
inspectable independently of the main connection's exports. `--step=clip
--debug` similarly preserves each `parent_fid`'s own
`{tmp_dir}/{name}_04_p{parent_fid}/` directory.
