# match

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md`/`docs/reference/extend.md` for rules `match` shares with other
tools.

## Inputs

- `match` MUST load and coverage-clean both the child layer and the
  parent/clip layer, the same way `extend`'s own inputs stage does (see
  `docs/reference/extend.md`).

## Assigning children to parents

- `match` MUST assign each child polygon to the single parent polygon it
  shares the largest overlapping area with.
- A tie between two candidate parents MUST be broken by the lower parent
  id.
- A child with no overlap with any parent MUST be dropped, not treated as
  fatal, and `match` MUST log a warning naming it -- this may signal a real
  data problem even though it isn't fatal. It MUST also be recorded in the
  issues report described under Outputs.

## Extending each group

- `match` MUST group children by their assigned parent, including a group
  of exactly one child.
- For each group, `match` MUST extend that group's children alone
  (boundary extraction, point/Voronoi generation, merging -- see
  `docs/reference/extend.md`). Clipping to the group's parent happens later,
  batched across all groups (see Clipping below), not inside this step.
- Each group's extension MUST run in an isolated process, separate from
  every other group and from `match`'s own process.
- A group whose extension fails MUST be dropped from the output, not
  treated as fatal to the whole run, and `match` MUST log an error naming
  it -- this may signal a real data problem even though it isn't fatal.
  `match` MUST raise only if every group fails to produce output. Every
  child belonging to a failed group MUST be recorded in the issues report
  described under Outputs.

## Clipping

- `match` MUST clip every group's reassembled, extended output to its own
  `parent_fid`'s geometry, per `docs/reference/clip.md`, one distinct
  `parent_fid` at a time, each in its own spawned OS subprocess.
- Unlike a failed group's extension, `match` MUST raise immediately if any
  `parent_fid`'s clip subprocess fails, aborting the whole run rather than
  dropping just that group.

## Stitching

- `match` MUST run one whole-layer coverage-clean pass over the clipped
  output, per `docs/reference/stitch.md`, using the same fixed gap-closing
  width as `extend`'s own merge stage (see `docs/reference/extend.md`), not
  a per-feature-scoped pass.

## Outputs

- `match`'s final output MUST pass the hard gate in `docs/reference/shared.md` (no
  overlap, no gap) before export.
- `match` MUST export the final merged layer.
- `match` MUST also export an issues report alongside it, listing every
  dropped child and every child belonging to a dropped group, so a human
  can audit what didn't make it into the output.
- The issues report MUST list, for every entry: a unique key, whether it
  is an unassigned child or a dropped-group child, the child's own fid and
  geometry, and, for a dropped-group child, the parent id its group was
  assigned to and the reason its group was dropped. A field that doesn't
  apply to an entry's kind MUST be absent.
- `match` MUST always produce the issues report, even when there are zero
  dropped children and zero dropped groups.

## Configuration (`api.match.match()` / CLI)

- `match` MUST process exactly one child file and one parent/clip file per
  call.
- The output path MUST default to the child input path with a `_matched`
  suffix. The issues-report path MUST default to the output path with an
  `_issues` suffix.
- `match` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `groups`, `clip`,
  `stitch`, `outputs`; any other value MUST raise `ValueError`.
