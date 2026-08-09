# assign-one

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `assign-one` shares with other tools.

## Inputs

- `assign-one` MUST load the child layer(s) and the parent/clip layer raw,
  unlike `extend`'s own inputs stage: neither is coverage-checked or
  -cleaned before assigning. The child layer is expected to already be a
  finished `extend()` output, but `assign-one` does not verify this (see
  `docs/explanation/assign.md`).
- The child role MAY span multiple files (e.g. one `extend()` output per
  country), combined internally. The parent/clip layer MUST remain a
  single file.
- Every output row MUST carry a `source_file` column recording the exact
  path of the child file it came from.

## Assigning children to parents

- `assign-one` MUST assign every child from one input file to a single
  parent polygon, shared by the whole file: a file's children are one
  group (e.g. one country's admin2 units), not independently routed to
  whichever parent each one individually overlaps most.
- The file's parent MUST be whichever parent the largest number of that
  file's children intersect (a majority vote by count of intersecting
  children, not summed overlap area), so a handful of border-overshooting
  children cannot misassign a file whose other children overwhelmingly
  point to their true parent.
- A tie between two candidate parents MUST be broken by the lower parent id.
- A child that does not itself overlap its file's assigned parent MUST be
  dropped, not treated as fatal, and `assign-one` MUST log a warning
  naming it. A whole file with no child overlapping any parent MUST be
  dropped the same way. Either case MUST also be recorded in the issues
  report described under Outputs.

## Outputs

- `assign-one` MUST export every assigned child with its own `parent_fid`
  column attached, directly chainable into `clip`'s input contract.
- `assign-one` MUST NOT run the coverage hard gate in
  `docs/reference/shared.md` on its own output: an unclipped crosswalk is
  expected to still overlap/gap between neighboring children.
- `assign-one` MUST also export an issues report alongside it, listing
  every unassigned child (unique key, kind `unassigned`, child fid,
  `source_file`, geometry). `assign-one` MUST always produce the issues
  report, even when there are zero unassigned children.

## Configuration (`api.assign_one.assign_one()` / CLI)

- `assign-one` MUST accept one or more child files and exactly one
  parent/clip file per call.
- With a single child file, the output path MUST default to that input
  path with an `_assigned` suffix. With multiple child files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `assign-one` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `outputs`; any other
  value MUST raise `ValueError`.
