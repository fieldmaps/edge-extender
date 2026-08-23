# crosswalk

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `crosswalk` shares with other tools.

## Matching and renaming

- `crosswalk` MUST map a source-column -> target-schema crosswalk exactly
  as standalone `map` does (see `docs/reference/map.md`): the same
  matching passes, noise-column exclusion, and output ordering rules
  apply unchanged, `crosswalk` calls `map`'s own matching stage directly
  rather than owning separate logic.
- `crosswalk` MUST then apply that freshly-generated crosswalk exactly as
  standalone `refactor` does (see `docs/reference/refactor.md`): the same
  coverage-validation, renaming, and dropping rules apply unchanged,
  `crosswalk` calls `refactor`'s own validation and rename stages directly.

## Outputs

- `crosswalk` MUST always produce both the crosswalk CSV (same shape as
  standalone `map`'s output) and the mapped output file (same shape as
  standalone `refactor`'s output).
- `crosswalk` performs no topology hard gate at all; neither underlying
  stage touches geometry.

## Configuration (`api.crosswalk.crosswalk()` / CLI)

- `crosswalk` MUST process exactly one input file per call.
- The mapped-output path MUST default to the input path with a `_mapped`
  suffix. The crosswalk path MUST default to the input path with a
  `_crosswalk` stem suffix and a `.csv` extension.
- `crosswalk` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `map`, `apply`, `outputs`;
  any other value MUST raise `ValueError`.
- To iterate on a `crosswalk`-generated crosswalk (hand-edit it, then
  re-apply), re-run standalone `refactor` on the written crosswalk file;
  re-running `crosswalk` always maps fresh, discarding any hand edits.
