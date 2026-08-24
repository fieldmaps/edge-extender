# edge-match

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md`/`docs/reference/edge_extend.md` for rules `edge-match` shares with other
tools.

## Inputs

- `edge-match` MUST load and coverage-clean both the child layer and the
  parent/clip layer, the same way `edge-extend`'s own inputs stage does (see
  `docs/reference/edge_extend.md`).

## Assigning children to parents

- `edge-match` MUST assign each child polygon to the single parent polygon it
  shares the largest overlapping area with.
- A tie between two candidate parents MUST be broken by the lower parent
  id.
- A child with no overlap with any parent MUST be dropped, not treated as
  fatal, and `edge-match` MUST log a warning naming it, since this may signal a real
  data problem even though it isn't fatal. It MUST also be recorded in the
  issues report described under Outputs.

## Extending each group

- `edge-match` MUST group children by their assigned parent, including a group
  of exactly one child.
- For each group, `edge-match` MUST extend that group's children alone
  (boundary extraction, point/Voronoi generation, merging; see
  `docs/reference/edge_extend.md`). Clipping to the group's parent happens later,
  batched across all groups (see Clipping below), not inside this step.
- Each group's extension MUST run in an isolated process, separate from
  every other group and from `edge-match`'s own process.
- A group whose extension fails MUST be dropped from the output, not
  treated as fatal to the whole run, and `edge-match` MUST log an error naming
  it, since this may signal a real data problem even though it isn't fatal.
  `edge-match` MUST raise only if every group fails to produce output. Every
  child belonging to a failed group MUST be recorded in the issues report
  described under Outputs.

## Clipping

- `edge-match` MUST clip every group's reassembled, extended output to its own
  `parent_fid`'s geometry, per `docs/reference/edge_clip.md`, one distinct
  `parent_fid` at a time, each in its own spawned OS subprocess.
- Unlike a failed group's extension, `edge-match` MUST raise immediately if any
  `parent_fid`'s clip subprocess fails, aborting the whole run rather than
  dropping just that group.

## Stitching

- `edge-match` MUST run one whole-layer coverage-clean pass over the clipped
  output, per `docs/reference/edge_stitch.md`, using the same fixed gap-closing
  width as `edge-extend`'s own merge stage (see `docs/reference/edge_extend.md`), not
  a per-feature-scoped pass.

## Outputs

- `edge-match`'s final output MUST pass the hard gate in
  `docs/reference/shared.md` (no overlap, no gap at or below
  `SNAP_TOLERANCE`) before export. A wider leftover gap does not block
  export (see `docs/adr/0035`).
- `edge-match` MUST export the final merged layer.
- `edge-match` MUST also export an issues report alongside it, using the shared
  schema in `docs/reference/shared.md`, listing every dropped child, every
  child belonging to a dropped group, and every leftover gap wider than
  `SNAP_TOLERANCE`, so a human can audit what didn't make it into the
  output or what may need review.
- For an `unassigned`/`dropped_group` row, `unit_a` MUST hold the child's
  own fid; for a `dropped_group` row, `parent_fid` and `reason` MUST record
  the group's assigned parent and drop reason. For a `gap` row, `area_m2`,
  `max_width_m`, and `thinness_ratio` MUST be populated instead. A field
  that doesn't apply to a row's kind MUST be null.
- `edge-match` MUST produce the issues report only when it has at least one
  row; when it would be empty, no file MUST be written (and a stale file
  from a previous run at that path MUST be removed).

## Configuration (`api.edge_match.match()` / CLI)

- `edge-match` MUST process exactly one child file and one parent/clip file per
  call.
- The output path MUST default to the child input path with a `_matched`
  suffix. The issues-report path MUST default to the output path with an
  `_issues` suffix.
- `edge-match` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `groups`, `edge-clip`,
  `edge-stitch`, `outputs`; any other value MUST raise `ValueError`.
- `edge-match` MAY accept `match_column`/`parent_match_column`/`child_match_column`
  to override spatial assignment with an exact code join (see
  `docs/reference/shared.md`, `docs/explanation/assign.md`).
