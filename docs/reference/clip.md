# clip

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `clip` shares with other tools.

## Inputs

- `clip` MUST load the children layer and the parent/clip layer raw,
  neither coverage-checked nor -cleaned.
- `clip` MUST NOT require or read a `parent_fid` column on the children
  layer.

## Assignment

- `clip` MUST internally assign every child to exactly one parent before
  clipping, via `assign-one`'s per-file majority-vote strategy (see
  `docs/explanation/assign.md`): every child in the input file is forced
  onto the one parent that wins a majority vote by count of the file's
  children, not evaluated per child.
- A child that does not agree with its file's majority-vote parent MUST be
  dropped, not clipped against the wrong parent.

## Clipping

- `clip` MUST clip each row to its own `parent_fid`'s geometry via
  `ST_Intersection`, one distinct `parent_fid` at a time, each in its own
  spawned OS subprocess.
- Within one `parent_fid`'s subprocess, `clip` MUST grid-subdivide that
  parent's boundary into small tiles before intersecting once its vertex
  count exceeds an adaptive threshold, sizing the tile grid from that
  parent's own vertex density, and MUST join children to tiles via bbox
  comparison, never `ST_Intersects`.
- A child whose clipped result is empty MUST be dropped from the output.
- `clip` MUST raise immediately on the first `parent_fid` whose subprocess
  fails, aborting the whole run rather than skipping just that `parent_fid`.

## Outputs

- `clip` MUST NOT run the coverage hard gate in `docs/reference/shared.md`
  on its own output: closing seams between clipped pieces is `stitch`'s
  job, not `clip`'s.
- `clip` MUST raise `RuntimeError` if the clipped result has zero rows.
- `clip` MUST export the clipped layer.

## Configuration (`api.clip.clip()` / CLI)

- `clip` MUST process exactly one children file and exactly one
  parent/clip file per call.
- The output path MUST default to the children path with a `_clipped`
  suffix.
- `clip` MUST raise `FileExistsError` if the output exists and
  overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `clip`, `outputs`;
  any other value MUST raise `ValueError`.
