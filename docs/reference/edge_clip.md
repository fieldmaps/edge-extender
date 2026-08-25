# edge-clip

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `edge-clip` shares with other tools.

## Inputs

- `edge-clip` MUST load the children layer and the parent/clip layer raw,
  neither coverage-checked nor -cleaned.
- `edge-clip` MUST NOT require or read a `parent_fid` column on the children
  layer.
- `edge-clip` MUST accept exactly one children file and exactly one
  parent/clip file per call, a strict 1:1 primitive (see `docs/adr/0080`);
  batching many children files against one shared parent load is
  `edge-mosaic`'s job (see `docs/reference/edge_mosaic.md`).
- The output row MUST carry a `source_file` column recording the path of
  the children file it came from.

## Assignment

- `edge-clip` MUST internally assign every child to exactly one parent before
  clipping, via `assign-one`'s file-wide majority-vote strategy (see
  `docs/explanation/assign.md`): every child is forced onto the one parent
  that wins a majority vote by count, not evaluated per child.
- A child that does not agree with the file's majority-vote parent MUST be
  dropped, not clipped against the wrong parent.

## Clipping

- `edge-clip` MUST clip each row to its own `parent_fid`'s geometry via
  `ST_Intersection`, one distinct `parent_fid` at a time, each in its own
  spawned OS subprocess.
- Within one `parent_fid`'s subprocess, `edge-clip` MUST grid-subdivide that
  parent's boundary into small tiles before intersecting once its vertex
  count exceeds an adaptive threshold, sizing the tile grid from that
  parent's own vertex density, and MUST join children to tiles via bbox
  comparison, never `ST_Intersects`.
- A child whose clipped result is empty MUST be dropped from the output.
- `edge-clip` MUST raise immediately on the first `parent_fid` whose subprocess
  fails, aborting the whole run rather than skipping just that `parent_fid`.

## Outputs

- `edge-clip` MUST NOT run the coverage hard gate in `docs/reference/shared.md`
  on its own output: closing seams between clipped pieces is `edge-stitch`'s
  job, not `edge-clip`'s.
- `edge-clip` MUST raise `RuntimeError` if the clipped result has zero rows.
- `edge-clip` MUST export the clipped layer to the output file.

## Configuration (`api.edge_clip.clip()` / CLI)

- The output path MUST default to the input path with a `_clipped` suffix.
- `edge-clip` MUST raise `FileExistsError` if the output already exists and
  overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `edge-clip`, `outputs`;
  any other value MUST raise `ValueError`.
- `edge-clip` MAY accept `match_column`/`parent_match_column`/`child_match_column`
  to override spatial assignment with an exact code join (see
  `docs/reference/shared.md`, `docs/explanation/assign.md`); doing so gives
  `edge-clip` its only issues report, `issues_path`, defaulting to the
  output path with an `_issues` suffix.
- `edge-clip` MAY accept `carry_columns` (CLI: `--carry-column`) to copy
  named parent columns onto every matched child (see
  `docs/reference/shared.md`, `docs/adr/0077`).
