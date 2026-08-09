# assign-many

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `assign-many` shares with other tools.

## Inputs

- `assign-many` MUST load the child layer(s) and the parent/clip layer raw,
  unlike `extend`'s own inputs stage: neither is coverage-checked or
  -cleaned before assigning.
- The child role MAY span multiple files, combined internally. The
  parent/clip layer MUST remain a single file.
- Every output row MUST carry a `source_file` column recording the exact
  path of the child file it came from.

## Assigning children to parents

- `assign-many` MUST assign each child independently to the parent it
  shares the largest overlap area with, so one input file's children MAY
  scatter across many different parents.
- A tie between two candidate parents MUST be broken by the lower parent id.
- A child that does not overlap any parent MUST be dropped, not treated as
  fatal, and `assign-many` MUST log a warning naming it. This MUST also be
  recorded in the issues report described under Outputs.

## Outputs

- `assign-many` MUST export every assigned child with its own `parent_fid`
  column attached, directly chainable into `clip`'s input contract.
- `assign-many` MUST NOT run the coverage hard gate in
  `docs/reference/shared.md` on its own output: an unclipped crosswalk is
  expected to still overlap/gap between neighboring children.
- `assign-many` MUST also export an issues report alongside it, listing
  every unassigned child (unique key, kind `unassigned`, child fid,
  geometry). `assign-many` MUST always produce the issues report, even when
  there are zero unassigned children.

## Configuration (`api.assign_many.assign_many()` / CLI)

- `assign-many` MUST accept one or more child files and exactly one
  parent/clip file per call.
- With a single child file, the output path MUST default to that input
  path with an `_assigned` suffix. With multiple child files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `assign-many` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `outputs`; any other
  value MUST raise `ValueError`.
