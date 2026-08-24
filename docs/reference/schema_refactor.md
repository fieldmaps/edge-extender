# schema-refactor

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-refactor` shares with other tools.

## Inputs

- `schema-refactor` MUST read the input and reproject it to EPSG:4326 the same
  way every other tool does, via `core.io.read_and_reproject()`.
- `schema-refactor` MUST take a crosswalk CSV file (as written by `schema-map`, or a
  hand-edited copy of one): one row per source column with
  `source_column` and `target_column` columns.
- `schema-refactor` MUST raise `ValueError` if the crosswalk's `source_column`
  set does not exactly equal the input file's own column set, excluding
  any column matching `core.constants.is_noise_column()` (extra columns
  in either direction), catching a stale crosswalk or a mismatched input
  file rather than silently mis-mapping or dropping data.
- `schema-refactor` MUST raise `ValueError` if two source columns share the
  same non-null `target_column`, or if a `target_column` collides with a
  reserved name (`fid`, `geom`, `geometry`), rather than letting DuckDB
  silently disambiguate the output column names.
- `schema-refactor` MUST raise `ValueError` if the crosswalk file is not a CSV
  with a `source_column` column.
- A row with a blank `source_column` (a `schema-map`-written gap-row placeholder)
  MUST be skipped, not raise.
- `schema-refactor` MUST raise `ValueError` if the crosswalk lists the same
  `source_column` more than once.

## Renaming

- A source column whose `target_column` is null or empty MUST be dropped
  from the output.
- Every other source column MUST be renamed to its `target_column`.
- The geometry column MUST always pass through unchanged, regardless of
  the crosswalk.

## Outputs

- `schema-refactor` performs no topology hard gate at all; it only renames/drops
  columns, never touching geometry.

## Configuration (`api.schema_refactor.refactor()` / CLI)

- `schema-refactor` MUST process exactly one input file per call.
- The output path MUST default to the input path with a `_mapped` suffix.
- `schema-refactor` MUST raise `FileExistsError` if the output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `rename`, `outputs`; any
  other value MUST raise `ValueError`.
