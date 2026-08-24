# Refactor Explanation

`schema-refactor` takes a crosswalk file (written by `schema-map`, likely hand-edited
afterward) and actually renames/drops the input file's columns.
Splitting this from `schema-map` (`docs/explanation/schema_map.md`) is what gives
schema mapping a real human-review gate: nothing is ever renamed without
a human having seen and been able to edit the crosswalk first, matching
`hdx-cod-ab-ai`'s PRD requirement that no pipeline stage auto-applies
without confirmation.

## Usage

```sh
topo-tools schema-refactor example.geojson crosswalk.csv
```

```python
from topo_tools.api.schema_refactor import refactor

refactor("example.parquet", "crosswalk.csv", "example_mapped.parquet")
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_mapped` suffix.

Run `topo-tools schema-refactor --help` for the full, always-current option
list.

## Pipeline

1. **`_01_inputs`**: reads and reprojects to EPSG:4326 via the shared
   `core.io.read_and_reproject()` helper, then validates the crosswalk:
   its `source_column` set must exactly equal the input file's own column
   set. This catches both directions of mismatch, a stale crosswalk
   referencing a column the file no longer has, and a file column the
   crosswalk never decided about, rather than silently ignoring either.
2. **`_02_rename`**: builds one `SELECT` that renames every source column
   to its `target_column` and drops any column whose `target_column` is
   null/empty, writing `{name}_02`. The geometry column always passes
   through unchanged.
3. **`_03_outputs`**: exports `{name}_02` to the output file. No hard
   gate: `schema-refactor` only renames/drops columns, it never touches
   geometry.

## Crosswalk semantics

A `target_column` of `null`/empty means "drop this column"; anything else
is the new name to rename it to, including the column's own original name
if the intent is simply to retain it unchanged. `schema-map` always
proposes retaining an unmatched column under its original name rather
than leaving it ambiguous, so an unedited crosswalk from `schema-map`
never drops data; dropping is always an explicit edit a human makes.

`_01_inputs` rejects a hand-edited crosswalk where two source columns
share the same non-null `target_column`, or where a `target_column` collides
with a reserved name (`fid`/`geom`/`geometry`), raising before any rename
runs. Without this check, DuckDB doesn't error on a duplicate output column
name; it silently disambiguates by appending `_1`, `_2`, etc., which would
rename the user's requested column away from the name they asked for with
no warning.
