# schema-crosswalk

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-crosswalk` shares with other tools.

## Matching and renaming

- `schema-crosswalk` MUST map a source-column -> target-schema crosswalk exactly
  as standalone `schema-map` does (see `docs/reference/schema_map.md`): the same
  matching passes, noise-column exclusion, and output ordering rules
  apply unchanged, `schema-crosswalk` calls `schema-map`'s own matching stage directly
  rather than owning separate logic.
- `schema-crosswalk` MUST then apply that freshly-generated crosswalk exactly as
  standalone `schema-refactor` does (see `docs/reference/schema_refactor.md`): the same
  coverage-validation, renaming, and dropping rules apply unchanged,
  `schema-crosswalk` calls `schema-refactor`'s own validation and rename stages directly.

## Outputs

- `schema-crosswalk` MUST always produce both the crosswalk CSV (same shape as
  standalone `schema-map`'s output) and the mapped output file (same shape as
  standalone `schema-refactor`'s output).
- `schema-crosswalk` performs no topology hard gate at all; neither underlying
  stage touches geometry.

## Configuration (`api.schema_crosswalk.crosswalk()` / CLI)

- `schema-crosswalk` MUST process exactly one input file per call.
- The mapped-output path MUST default to the input path with a `_mapped`
  suffix. The crosswalk path MUST default to the input path with a
  `_crosswalk` stem suffix and a `.csv` extension.
- `schema-crosswalk` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `schema-map`, `apply`, `outputs`;
  any other value MUST raise `ValueError`.
- To iterate on a `schema-crosswalk`-generated crosswalk (hand-edit it, then
  re-apply), re-run standalone `schema-refactor` on the written crosswalk file;
  re-running `schema-crosswalk` always maps fresh, discarding any hand edits.
