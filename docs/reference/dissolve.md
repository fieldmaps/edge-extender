# dissolve

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `dissolve` shares with other tools.

## Inputs

- `dissolve` MUST read the input and reproject it to EPSG:4326.
- `dissolve` MUST raise `ValueError` if any `group_by` column is missing
  from the input's schema.

## Dissolving

- `dissolve` MUST group rows by the exact column(s) given in `group_by`,
  unioning their geometry per group with `ST_Union_Agg` followed by
  `ST_MakeValid`. A NULL value in a `group_by` column MUST form its own
  group like any other value (DuckDB's native `GROUP BY` semantics,
  matching GDAL's `combine --group-by`); `dissolve` MUST NOT raise or
  filter rows based on `group_by` nullness.
- Every column not in `group_by`, `exclude`, or (when `target_schema` is
  given) a schema-derived finer-level column MUST be resolved
  automatically: `dissolve` MUST verify the column has at most one
  distinct non-NULL value within every group, retaining it (`any_value`)
  if so and dropping it (logging a warning naming every dropped column) if
  not. `exclude` and schema-derived columns MUST be dropped unconditionally,
  before this check runs, and MUST NOT trigger the dropped-column warning.

## Outputs

- `dissolve`'s final output MUST pass the hard gate in
  `docs/reference/shared.md` (no overlap; a gap at or below
  `SNAP_TOLERANCE` blocks export, a wider one does not).
- `dissolve` MUST export the dissolved layer.
- `dissolve` MUST also export an issues report alongside it, using the
  shared schema in `docs/reference/shared.md`, listing every leftover gap
  wider than `SNAP_TOLERANCE`. `area_m2`, `max_width_m`, and
  `thinness_ratio` MUST be populated for each row; every other column MUST
  be null.
- `dissolve` MUST produce the issues report only when it has at least one
  row; when it would be empty, no file MUST be written (and a stale file
  from a previous run at that path MUST be removed).

## Configuration (`api.dissolve.dissolve()` / CLI)

- `dissolve` MUST process exactly one input file per call.
- `group_by` MUST be a non-empty list of column names; an empty list MUST
  raise `ValueError`. The CLI's `--group-by` MAY be repeated and/or
  comma-separated.
- The output path MUST default to the input path with a `_dissolved`
  suffix. The issues-report path MUST default to the output path with an
  `_issues` suffix.
- `dissolve` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `dissolve`, `outputs`; any
  other value MUST raise `ValueError`.
- `exclude`, if given, MUST be a list of column names dropped
  unconditionally before the constancy check; a name not present in the
  input's schema MUST be ignored, not raise. The CLI's `--exclude` MAY be
  repeated and/or comma-separated.
- `target_schema_path` (`api.dissolve.dissolve()`; CLI: `--target-schema`),
  if given, MUST be a target-schema YAML path (the same format
  `schema-map`/`schema-fill` use). `dissolve` MUST detect
  `group_by`'s own deepest matching level and unconditionally exclude
  every column at a finer level, raising `ValueError` if no `group_by`
  column matches any detected level.
