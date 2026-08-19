# schema-apply

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-apply` shares with other
tools.

## Inputs

- `schema-apply` MUST read the input and reproject it to EPSG:4326 the
  same way every other tool does, via `core.io.read_and_reproject()`.
- `schema-apply` MUST take a crosswalk JSON file (as written by
  `schema-propose`, or a hand-edited copy of one): a list of objects with
  `source_column` and `target_column` keys.
- `schema-apply` MUST raise `ValueError` if the crosswalk's `source_column`
  set does not exactly equal the input file's own column set (extra
  columns in either direction), catching a stale crosswalk or a
  mismatched input file rather than silently mis-mapping or dropping data.
- `schema-apply` MUST raise `ValueError` if two source columns share the
  same non-null `target_column`, or if a `target_column` collides with a
  reserved name (`fid`, `geom`, `geometry`), rather than letting DuckDB
  silently disambiguate the output column names.
- `schema-apply` MUST raise `ValueError` (not a raw `TypeError`/`KeyError`)
  if the crosswalk file is not a JSON list of objects each carrying a
  `source_column` key.
- `schema-apply` MUST raise `ValueError` if the crosswalk lists the same
  `source_column` more than once.

## Renaming

- A source column whose `target_column` is null or empty MUST be dropped
  from the output.
- Every other source column MUST be renamed to its `target_column`.
- The geometry column MUST always pass through unchanged, regardless of
  the crosswalk.

## Outputs

- `schema-apply` performs no topology hard gate at all; it only
  renames/drops columns, never touching geometry.

## Configuration (`api.schema_apply.schema_apply()` / CLI)

- `schema-apply` MUST process exactly one input file per call.
- The output path MUST default to the input path with a `_mapped` suffix.
- `schema-apply` MUST raise `FileExistsError` if the output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `rename`, `outputs`; any
  other value MUST raise `ValueError`.
