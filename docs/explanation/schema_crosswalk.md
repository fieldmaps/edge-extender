# Crosswalk Explanation

`schema-crosswalk` runs `schema-map` immediately followed by `schema-refactor` in one call,
mirroring the `topo-clean` (wraps `topo-detect` + fix) pattern: the two underlying
tools remain available standalone, and this composite just chains them
for a fast first pass, so a user can see mapped values right away and
judge whether the proposed crosswalk is correct, rather than reading a
crosswalk CSV in the abstract.

## Usage

```sh
topo-tools schema-crosswalk example.geojson
```

```python
from topo_tools.api.schema_crosswalk import crosswalk

crosswalk("example.parquet")
```

`TARGET_SCHEMA_FILE`, `OUTPUT_FILE`, and `CROSSWALK_FILE` are all
positional and optional, with the same defaults as standalone `schema-map`
(crosswalk path) and `schema-refactor` (mapped-output path).

To iterate: hand-edit the written crosswalk CSV, then re-run standalone
`schema-refactor` on it. Re-running `schema-crosswalk` always maps fresh from scratch,
so it never sees hand edits from a prior run.

## Pipeline

1. **`_01_inputs`**: reuses `core.schema_map._01_inputs.main()` directly, reading
   and reprojecting into `{name}_01`.
2. **`_02_map`**: reuses `core.schema_map._02_map.main()` directly, writing the
   crosswalk to `{name}_02` exactly as standalone `schema-map` would.
3. **`_03_apply`** (new, `core/schema_crosswalk/_03_apply.py`): applies `{name}_02`
   to `{name}_01` via `core.schema_refactor`'s stages, see "Table namespacing"
   below.
4. **`_04_outputs`** (new, `core/schema_crosswalk/_04_outputs.py`): exports the
   crosswalk CSV by reusing `core.schema_map._03_outputs.main()`, and the mapped
   file by reusing `core.schema_refactor._03_outputs.main()`.

## Table namespacing

`core.schema_map._02_map.main()` and `core.schema_refactor._02_rename.main()` each
hardcode their own output as `"{name}_02"` for entirely different data
(the crosswalk proposal vs. the renamed/mapped table); reusing both back
to back under the same `name` would silently overwrite one with the
other. `_03_apply.py` avoids this by giving the apply half of the
pipeline a distinct sub-namespace, `f"{name}_apply"`: it creates
`"{name}_apply_01"` as a DuckDB **view** over the already-loaded
`"{name}_01"`, rather than a copy, respecting this project's
memory-constrained deployment targets. `core.schema_refactor._02_rename.main()`
then runs completely unmodified against `name=f"{name}_apply"`, reading
the view as if it were its own `{name}_01`. The view is dropped
immediately after the rename stage finishes with it (not deferred to the
outputs stage): DuckDB's `DROP TABLE IF EXISTS`, which
`core.schema_refactor._03_outputs.main()`'s own cleanup uses, raises a Catalog
Error against an object that's actually a view rather than silently
no-op'ing, so the view must not still exist by the time that cleanup
runs.

Before applying, `_03_apply.py` reads `{name}_02`'s rows, excluding any
`NULL`-`source_column` gap row (the same exclusion a human hand-editing a
crosswalk would apply before handing it to standalone `schema-refactor`), then
calls `core.schema_refactor._01_inputs.validate_and_materialize_crosswalk()`
directly. This re-validates that the crosswalk exactly covers the
non-noise columns, a real safety-net check rather than just plumbing: a
fresh `schema-map`-generated crosswalk should always satisfy it by construction,
so a failure here would mean a bug in `schema-map` itself, caught immediately
instead of silently propagating into a wrong renamed output.

## Not modeled in v1

- `schema-crosswalk` cannot resume from a hand-edited crosswalk; it always maps
  fresh. The iteration workflow (hand-edit, then re-apply) goes through
  standalone `schema-refactor`, not `schema-crosswalk`, by design (see
  `docs/reference/schema_crosswalk.md`).
