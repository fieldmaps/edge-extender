# mosaic

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md`/`docs/reference/match.md` for rules `mosaic` shares with other
tools.

## Inputs

- `mosaic` MUST load the child layer and the parent/clip layer raw,
  unlike `extend`'s own inputs stage: neither is coverage-checked or
  -cleaned before assign/clip. The child layer is expected to already be a
  finished `extend()` output, but `mosaic` does not verify this (see
  `docs/explanation/mosaic.md`).
- Unlike every other tool here, the child role MAY span multiple files
  (e.g. one `extend()` output per country), combined internally. The
  parent/clip layer MUST remain a single file.
- Every output row MUST carry a `source_file` column recording the exact
  path of the child file it came from.

## Assigning children to parents

- `mosaic` MUST assign every child from one input file to a single parent
  polygon, shared by the whole file: a file's children are one group
  (e.g. one country's admin2 units), not independently routed to whichever
  parent each one individually overlaps most.
- The file's parent MUST be whichever parent the largest number of that
  file's children intersect (a majority vote by count of intersecting
  children, not summed overlap area), so a handful of border-overshooting
  children cannot misassign a file whose other children overwhelmingly
  point to their true parent.
- A tie between two candidate parents MUST be broken by the lower parent id.
- A child that does not itself overlap its file's assigned parent MUST be
  dropped, not treated as fatal, and `mosaic` MUST log a warning naming it.
  A whole file with no child overlapping any parent MUST be dropped the
  same way. Either case MUST also be recorded in the issues report
  described under Outputs.

## Clipping

- `mosaic` MUST NOT re-run Voronoi extension on any child; the child
  layer is assumed already extended.
- `mosaic` MUST clip each assigned child to its own assigned parent's
  geometry via `ST_Intersection`, one distinct assigned parent fid at a
  time, each in its own spawned OS subprocess (see
  `docs/explanation/mosaic.md`).
- Within one parent fid's subprocess, `mosaic` MUST grid-subdivide that
  parent's boundary into small tiles before intersecting once its vertex
  count exceeds an adaptive threshold, sizing the tile grid from that
  parent's own vertex density, and MUST join children to tiles via bbox
  comparison, never `ST_Intersects`.
- A child whose clipped result is empty MUST be dropped from the output.
- `mosaic` MUST raise if zero children were ever assigned to any parent.

## Stitching

- `mosaic` MUST run one whole-layer coverage-clean pass over the clipped
  output, per `docs/reference/stitch.md`, using the same fixed gap-closing
  width as `extend`'s own merge stage (see `docs/reference/extend.md`), not
  a per-feature-scoped pass.

## Outputs

- `mosaic`'s final output MUST pass the hard gate in `docs/reference/shared.md`
  (no overlap, no gap) before export.
- `mosaic` MUST export the final merged layer.
- `mosaic` MUST also export an issues report alongside it, listing every
  unassigned child, so a human can audit what didn't make it into the
  output.
- The issues report MUST list, for every entry: a unique key, the kind
  (`unassigned`), the child's own fid and geometry. Parent id and reason
  fields MUST be absent (null), since `mosaic` has no per-group failure
  concept.
- `mosaic` MUST always produce the issues report, even when there are zero
  unassigned children.

## Configuration (`api.mosaic.mosaic()` / CLI)

- `mosaic` MUST accept one or more child files and exactly one parent/clip
  file per call. The CLI additionally accepts `--input` (repeatable and
  comma-separable) alongside the glob-capable `INPUT_FILE` positional, both
  usable together, matching `clip`'s own `--input` idiom.
- With a single child file, the output path MUST default to that input
  path with a `_mosaicked` suffix. With multiple child files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `mosaic` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `clip`, `stitch`,
  `outputs`; any other value MUST raise `ValueError`.
