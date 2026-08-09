# clip

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `clip` shares with other tools.

## Inputs

- `clip` MUST load the children layer and the parent/clip layer raw,
  neither coverage-checked nor -cleaned.
- `clip` MUST NOT require or read a `parent_fid` column on the children
  layer.
- Unlike every tool here except `mosaic`, the children role MAY span
  multiple files, sharing a single load of the parent/clip layer; the
  parent/clip layer itself MUST remain a single file.
- Every output row MUST carry a `source_file` column recording the exact
  path of the children file it came from.

## Assignment

- `clip` MUST internally assign every child to exactly one parent before
  clipping, via `assign-one`'s per-file majority-vote strategy (see
  `docs/explanation/assign.md`): every child in one children file is forced
  onto the one parent that wins a majority vote by count of that file's
  children, not evaluated per child. With multiple children files, each is
  its own independent majority-vote group, not one vote across all of them.
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
- With multiple children files, `clip` MUST raise `RuntimeError` naming
  any children file whose rows are all gone after clipping, before writing
  any output file: a multi-file call MUST either fully succeed or write
  nothing, never a partial set of outputs.
- `clip` MUST export the clipped layer, one output file per children file.

## Configuration (`api.clip.clip()` / CLI)

- `clip` MUST accept one or more children files and exactly one
  parent/clip file per call.
- With a single children file, the output path MUST default to that
  input path with a `_clipped` suffix. With multiple children files,
  `output_paths` MUST be given explicitly as a list the same length as
  `children_paths`, paired by position; `clip` MUST raise `ValueError` on
  a length mismatch. There is no auto-naming or output-directory
  convention for the multi-file case.
- With multiple children files, `name` (the run's internal table/tmp-file
  identifier) MUST be given explicitly; `clip` MUST raise `ValueError` if
  it is omitted, since there is no single input path to derive one from.
- `clip` MUST raise `FileExistsError` if any output already exists and
  overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `clip`, `outputs`;
  any other value MUST raise `ValueError`.
- The CLI additionally accepts `--input`/`--output` (each repeatable and
  comma-separable), appending more children/output pairs beyond the first
  positional pair; `--name` is required whenever `--input` is given.
