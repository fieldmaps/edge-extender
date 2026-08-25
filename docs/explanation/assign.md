# Assign Explanation

`assign-many` and `assign-one` are two internal crosswalk strategies in
`core/assign/`, picked between by `edge-match` (`assign-many`) and `edge-mosaic`
(`assign-one`); neither is a standalone CLI/API tool. Both build a
`(child_fid, parent_fid)` pairing from a bbox-prefiltered, part-exploded
overlap-area join; they differ only in how that pairing gets finalized
once per-pair shared area is known. The right one to use is decided by
the input's geometry state, not by which tool you're eventually headed
toward:

- **`assign-many`**: each child decides independently which parent it
  overlaps most; one input file's children MAY scatter across **many**
  different parents. Correct for raw/unextended geometry, where a child
  can only ever overlap its true parent (there is no overshoot to
  misassign it).
- **`assign-one`**: every child in one input file is forced onto **one**
  shared parent, chosen by majority vote of that file's children. Needed
  for already-extended (post-`edge_extend()`, overshoot) geometry, where a
  handful of border-crossing children could otherwise plurality-assign
  themselves to the wrong neighboring parent.

This is a decision-granularity distinction (per-child vs. per-file), not a
tool-of-origin one: `assign-many` is `edge-match`'s assignment logic,
`assign-one` is `edge-mosaic`'s.

## Modules

`core/assign/` has no `api.*()`/CLI pipeline of its own; every function
below is called directly by another tool's own `api.*()` orchestrator
(`api.edge_mosaic`, `api.edge_clip`, `api.edge_match`), never from inside
`core.edge_mosaic`/`core.edge_match` themselves.

`core/assign/_inputs.py` loads the single parent/clip layer raw via
`core.io.read_and_reproject`, and the (possibly multi-file) child layer via
one combined query built from `core.io.reproject_select_sql()` per file
(`UNION ALL BY NAME`, no table-per-file materialization, see
`docs/adr/0044`); neither is coverage-checked nor -cleaned (consistent
with `edge-clip`/`edge-stitch`; these are all purely mechanical primitives). Every
child row is tagged with a `source_file` column recording the exact path
it came from (basename alone can't distinguish same-named files across
directories).
`api.edge_mosaic` and standalone `api.edge_clip` (its multi-file loop, see
`docs/explanation/edge_clip.md`) both call its `load_children()`/
`load_parent()` directly, since ADR-0023 split those apart; `api.edge_match`
loads its own children via `core.edge_match._01_inputs` instead.

`_many.py` / `_one.py` hold the actual assignment logic (see below):
`api.edge_match` calls `core.assign.assign_many()`, `api.edge_mosaic` and
standalone `api.edge_clip` both call `core.assign.assign_one()`, all directly
on their own already-loaded tables. `edge-mosaic` calls it once per run;
`edge-clip`'s multi-file loop calls it once per children file, reusing a
cached parent-tile decomposition across every call (see below and
`docs/adr/0024`). Neither function runs a coverage hard gate: an unclipped
crosswalk is expected to still overlap/gap between neighboring children,
that's `edge-clip`'s and `edge-stitch`'s job downstream.

## `assign_many`: largest-overlap assignment

Both layers are exploded into parts (`UNNEST(ST_Dump(geom))`) before
computing bbox candidates, a multi-part parent (a country with offshore
islands) would otherwise get one bbox spanning everything and defeat the
prefilter. Shared area per `(child, parent)` fid pair is summed across
every part-pair (a multi-part child can overlap a multi-part parent in
more than one place), ranked in an equal-area CRS (`EQUAL_AREA_CRS`)
rather than raw EPSG:4326 degree-area, which would bias plurality
assignment toward higher-latitude parents. Only the intersection geometry
is transformed, not the whole layer, to bound the cost.

```sql
ROW_NUMBER() OVER (PARTITION BY child_fid ORDER BY shared_area DESC, parent_fid ASC)
```

picks the plurality parent per child; ties break on the lowest parent fid.
Children with zero overlap with any parent are dropped with a logged
warning, not an error.

## `assign_one`: per-file majority-vote assignment

`assign_one` cannot use `assign_many`'s pairs join unmodified: it runs
against already-extended (often massively overshot) geometry, and a plain
`ST_Intersection`-based area-sum join against a huge single parent part
(e.g. a country-scale admin0 polygon) is exactly the failure mode `edge-clip`
itself grid-tiles around. So `assign_one` builds its own pairs table
(`_build_pairs`), reusing `core.edge_clip.subdivide_boundary` to tile any
parent part at or above `CLIP_TILE_MIN_VERTICES` before intersecting, the
same threshold and tiling logic `edge-clip` uses.

That tiling is pure parent geometry, independent of which children are
loaded, so it's split into its own function, `prepare_parent_tiles()`. A
caller processing one children file per run (`edge-mosaic`, single-file `edge-clip`)
never notices: `assign_one()`'s default `use_cached_tiles=False` calls it
once internally, same as before. `edge-clip`'s multi-file loop instead calls
`prepare_parent_tiles()` once before iterating and passes
`use_cached_tiles=True` on every file's `assign_one()` call, so the same
parent's tiles aren't grid-subdivided from scratch on every one of
possibly hundreds of files. See `docs/adr/0024` for the profiling
discrepancy that motivated this split.

For each `source_file`, `assign_one` counts how many of that file's children
intersect each candidate parent (a count of intersecting children, not
summed overlap area) and assigns every child in the file to whichever
parent wins that count, since a single file's children are always one
group. This guards against cross-country border overshoot misassigning a
file by per-child area alone; see `docs/adr/0019-mosaic-per-file-majority-vote.md`
for why a per-child rule isn't enough and what it was measured to break.

## Code-column join (optional)

Both `assign_many` and `assign_one` accept optional `parent_match_column`/
`child_match_column` kwargs. `None` (the default) keeps `_02_assign`'s
schema and values exactly as before, `child_fid`/`parent_fid` only, no
behavior change. When both are given, the existing spatial result above is
still always computed (it's needed as the cross-check), alongside an exact
code join restricted to `(child, parent)` pairs that actually overlap (a
code match against a non-overlapping parent doesn't count). The code result
wins whenever one exists; `_02_assign` gains two more columns recording
which path won:

- `assignment_method`: `'code'` when a code match existed, `'spatial_fallback'`
  when it fell back to the spatial result.
- `spatial_agrees`: for `method='code'` rows, whether the spatial result
  agreed (`True`)/disagreed (`False`) with the code match; `NULL` for
  `spatial_fallback` rows.

`assign_many` computes this per child (its usual per-child plurality feeds
the cross-check); `assign_one` computes it per source file (its usual
per-file majority vote feeds the cross-check, so every child in a
code-mismatched or code-fallback file shares the same `assignment_method`).
Neither function derives issues rows itself; that's each calling
`api.*()`'s job (`kind='code-mismatch'`/`'code-fallback'`, see
`docs/reference/shared.md`). See `docs/adr/0045` for why code wins on
disagreement instead of spatial, and why an unmatched code falls back
instead of dropping the child/file.

## Carry-forward columns (optional)

Both `assign_many` and `assign_one` accept an optional `carry_columns` list
of parent column names. `None` (the default) leaves `_02_assign`'s schema
unchanged. When given, each name is projected from `{name}_parent_01` onto
every matched child row, joined on the already-resolved `parent_fid` (after
any code-column join above has picked a winner), so it costs one extra join
regardless of which path assigned the parent. Column names are always
caller-specified, never inferred from either layer's schema, matching this
project's structural (not name/value-based) matching philosophy elsewhere
(see `docs/explanation/schema_map.md`). A name colliding with `_02_assign`'s
own reserved columns (`child_fid`, `parent_fid`, `assignment_method`,
`spatial_agrees`) raises `ValueError`; a name already present on the child
layer's own schema also raises `ValueError`, via an explicit `DESCRIBE`
pre-check, not left to the SQL layer to reject on its own (DuckDB silently
renames/dedups a duplicate `SELECT` column instead of erroring, see
`docs/adr/0077`).

Children with no parent match (`_02_unassigned`) never gain these columns.
A caller that keeps such rows in its own output regardless (e.g.
`edge-mosaic`'s `--merge`, see `docs/explanation/edge_mosaic.md`) gets
`NULL` for all of them automatically via that caller's own `UNION ALL BY
NAME`.

## Comparison

| | `assign-many` | `assign-one` |
| --- | --- | --- |
| Decision granularity | Per child | Per source file |
| Input assumption | Raw, unextended geometry | Already-extended (overshoot) geometry |
| Vote signal | N/A (each child stands alone) | Count of intersecting children per file |
| Misassignment risk | None from overshoot (there is none) | A file too small to form a real majority (single-child file, tied vote) |

## Caveats

**`assign-one` runs against overshoot geometry.** It never sees a child's
pre-extension footprint, only the already-extended geometry, so the bbox
prefilter is less selective than `assign-many`'s, and in principle the
per-child overlap signal underlying the vote could be skewed by a child
whose overshoot bulges further into a neighboring parent than into its
true one. The per-file majority vote mitigates this because a file's other,
unaffected children still outvote a single misbehaving one by count, but
a single-child file has no other vote to correct it, and a tied vote (e.g.
a two-child file split one-and-one between two parents) falls back to the
lower parent id rather than any geometric signal.
