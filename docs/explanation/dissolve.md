# Dissolve Explanation

`dissolve` aggregates a fine polygon layer into a coarser one by grouping on
one or more attribute columns (typically ancestor admin-level code columns,
e.g. `adm2_pcode`+`adm1_pcode` to collapse an admin3 layer into admin2),
unioning each group's geometry into a single feature.

## Usage

```sh
topo-tools dissolve adm3.geojson --group-by adm2_pcode
```

```python
from topo_tools import dissolve

dissolve("adm3.parquet", group_by=["adm2_pcode"])
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_dissolved` suffix.

Run `topo-tools dissolve --help` for the full, always-current option list.

## Pipeline

1. **`_01_inputs`**: loads and reprojects the input via
   `core.io.read_and_reproject`, then validates that every `group_by`
   column actually exists in the input's schema, raising early rather than
   failing deep inside the aggregate query.
2. **`_02_dissolve`**: `exclude` and, when `target_schema` is given, every
   column `_schema_derived_exclusions()` finds at a level finer than
   `group_by`'s own detected level (via `core/schema_map/_levels.py`'s
   `detect_levels()`/`column_families()`) are folded into the always-excluded
   set unconditionally, before anything else runs, so neither triggers the
   dropped-column warning below. Every remaining non-`group_by` column then
   resolves automatically: a single combined query checks whether each one
   is constant within every group, retaining it (`any_value`) if so and
   dropping it (with a warning naming every dropped column) if not. It then
   runs one
   `GROUP BY` + `ST_Union_Agg` + `ST_MakeValid` query — the same
   `ST_MakeValid(ST_Union_Agg(...)) ... GROUP BY` shape already used
   internally by `core/edge_extend/_04_voronoi.py`, generalized from a fixed
   `fid` grouping key to caller-supplied columns. A NULL value in a
   `group_by` column forms its own group here, DuckDB's native `GROUP BY`
   behavior, with no special-casing needed (see `docs/adr/0051`). This
   single-query shape is deliberately simpler than
   `core/edge_extend/_05_merge.py`'s bbox-prefiltered self-join: see
   `docs/adr/0047` for why that mitigation doesn't apply here.
3. **`_03_outputs`**: `check_valid_topology()`, relying on its default
   `gap_maximum_width=SNAP_TOLERANCE` (the same call `edge-match`/`edge-mosaic`/
   `edge-stitch` make), then export: raises on any overlap or a gap at or below
   `SNAP_TOLERANCE`, tolerates a wider one. A tolerated gap still gets
   reported as a `kind='gap'` row in the issues report and a warning log.

## Why non-group columns resolve automatically, with no override

`dissolve` is opinionated toward the admin-boundary-cleaning workflow it
was built for: dissolving a fine layer into a coarser one, where ancestor
name/pcode columns at or above the target level are genuinely constant per
group and the finer level's own columns are not. `dissolve` checks every
remaining column itself: a `COUNT(DISTINCT ...)` per group, collapsed to
one summary row per column via SQL aggregation so the check scales with
the number of columns, not the number of groups (a global admin4 dissolve
can have hundreds of thousands of groups). A column that's constant
everywhere is kept; one that isn't is dropped, with a warning naming it.
`exclude`/`target_schema` (see `docs/adr/0092`) only let a caller drop a
column *before* this check runs, for the one real gap the check itself
can't resolve (an all-NULL column carries no constancy signal distinguishing
a genuine finer-level field from a legitimate always-null one); they don't
add a way to force a varying column to survive.

There's no `keep`/aggregate-function override, and no way to force a
column to survive despite varying within a group (e.g. summing a per-child
population count): that's data enrichment, not boundary topology
maintenance, and outside what `dissolve` is for (see `docs/adr/0050`). A
pipeline that needs a summed/combined attribute alongside the dissolved
geometry runs that aggregation separately (e.g. a DuckDB `GROUP BY` query
against the same input, joined back on the `group_by` columns) rather than
through `dissolve` itself.

## No hardcoded admin-hierarchy naming convention

By default, `dissolve` never inspects column names to infer which are
"ancestor" columns; it inspects the data itself (constancy per group).
This keeps it schema-agnostic in the same spirit as `schema-map`, whose
target schema is itself a user-supplied YAML, not a naming convention
fixed inside `topo-tools`. A pipeline using any column-naming convention
gets the same automatic behavior without `dissolve` needing to know the
convention exists.

`target_schema` is the one explicit, opt-in exception: when a caller
supplies it, `dissolve` does match column names against that schema's
`code_field`/`name_field` templates, via the same
`core/schema_map/_levels.py` helpers `schema-fill` uses (see
`docs/adr/0092`). This only ever runs when a caller hands `dissolve` a
schema; the default, schema-free behavior above is unchanged.

## Portolan-scale profiling

The real target scale for this tool, `--debug` off, Apple Silicon/10 logical
cores:

| Run                              | Groups in / out    | Wall time | RSS peak | Result                              |
| --------------------------------- | ------------------- | --------- | -------- | ------------------------------------ |
| Global admin4→admin3 (`portolan/wld/adm4.parquet`, `--group-by adm3_pcode,adm2_pcode,adm1_pcode,adm0_pcode`) | 213,503 / 57,323 | 449s | 4.33 GB | No invalid edges; 30 gaps above the noise floor, tolerated and reported in the issues file |

The plain `GROUP BY` + `ST_Union_Agg` shape handles the full global admin4
scale in one pass, no bbox-prefiltered fallback needed (confirming the
`docs/adr/0047` decision).

**GDB-export gotcha, found while picking a test file:** an ad hoc
`gdal vector convert` from a zipped FileGDB (OpenFileGDB driver) of the same
213,503-row dataset introduced real topology defects, `has_invalid_edges()`
true, that the canonical `portolan/wld/adm4.parquet` GeoParquet (same row
count, same content) does not have. The GDB source logged `organizePolygons()
received a polygon with more than 100 parts` during conversion; that
part-reassembly heuristic is the suspected cause. Use the portolan catalog's
own GeoParquet files for topology-sensitive at-scale testing, not a
freshly-converted GDB export, even of nominally the same dataset.
