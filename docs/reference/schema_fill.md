# schema-fill

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-fill` shares with other tools.

## Inputs

- `schema-fill` MUST read the input and reproject it to EPSG:4326 the same
  way every other tool does, via `core.io.read_and_reproject()`.
- `schema-fill` MUST take the same target-schema YAML shape `schema-map`
  takes (top-level `name_field`/`code_field` string keys, each containing
  a `{n}` placeholder). If omitted, it MUST default to the bundled generic
  schema (`topo_tools/core/schema_map/data/default.yaml`).
- `schema-fill` MUST detect every admin level 1..N present via the
  schema's `code_field` prefix (e.g. `adm`), N being the deepest level
  column found, and MUST raise `ValueError` if any level in that 1..N
  range is missing its own code column, or if none is found at all.

## Filling

- For each admin-hierarchy column family sharing a level prefix and suffix
  (matched independently against the schema's own `name_field` prefix and
  `code_field` prefix, e.g. every `adm{n}_pcode`, every `adm{n}_name`),
  `schema-fill` MUST fill a NULL value at level `k` from the nearest
  non-NULL shallower level (`COALESCE` over levels `k, k-1, ..., 1`),
  leaving a value that is already non-NULL untouched.
- `schema-fill` MUST append one new column, named by `depth_column`
  (`--depth-column` on the CLI, defaulting to `adm_lvl`), stamping each
  row with the deepest level whose *original* (pre-fill) code column was
  non-NULL. This is the only signal distinguishing a genuine leaf-level
  row from a coarser row whose deeper columns were only ever filled down.
- `schema-fill` MUST NOT touch geometry, and MUST NOT drop or rename any
  column other than adding `depth_column`.

## Outputs

- `schema-fill` performs no topology hard gate at all; it only fills
  attribute columns and stamps a depth column, never touching geometry.
- `schema-fill` MUST export the filled layer to a single output file.

## Configuration (`api.schema_fill.fill()` / CLI)

- `schema-fill` MUST process exactly one input file per call.
- The output path MUST default to the input path with a `_fill` stem
  suffix.
- `schema-fill` MUST raise `FileExistsError` if the output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `fill`, `outputs`; any other
  value MUST raise `ValueError`.
- `schema-fill` MAY accept `depth_column`/`--depth-column`, overriding the
  `adm_lvl` default name for the stamped depth column.
