# edge-mosaic

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md`/`docs/reference/edge_match.md` for rules `edge-mosaic` shares with other
tools.

## Inputs

- `edge-mosaic` MUST load the child layer and the parent/clip layer raw,
  unlike `edge-extend`'s own inputs stage: neither is coverage-checked or
  -cleaned before assign/clip. The child layer is expected to already be a
  finished `edge_extend()` output, but `edge-mosaic` does not verify this (see
  `docs/explanation/edge_mosaic.md`).
- Unlike every other tool here, the child role MAY span multiple files
  (e.g. one `edge_extend()` output per country), combined internally. The
  parent/clip layer MUST remain a single file.
- Every output row MUST carry a `source_file` column recording the exact
  path of the child file it came from.

## Assigning children to parents

- `edge-mosaic` MUST assign every child from one input file to a single parent
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
  dropped, not treated as fatal, and `edge-mosaic` MUST log a warning naming it.
  A whole file with no child overlapping any parent MUST be dropped the
  same way, unless `merge_columns` is truthy (see Configuration), in which
  case that whole file's own geometry is kept unclipped instead. Either
  case MUST also be recorded in the issues report described under
  Outputs.

## Clipping

- `edge-mosaic` MUST NOT re-run Voronoi extension on any child; the child
  layer is assumed already extended.
- `edge-mosaic` MUST clip each assigned child to its own assigned parent's
  geometry via `ST_Intersection`, one distinct assigned parent fid at a
  time, each in its own spawned OS subprocess (see
  `docs/explanation/edge_mosaic.md`).
- Within one parent fid's subprocess, `edge-mosaic` MUST grid-subdivide that
  parent's boundary into small tiles before intersecting once its vertex
  count exceeds an adaptive threshold, sizing the tile grid from that
  parent's own vertex density, and MUST join children to tiles via bbox
  comparison, never `ST_Intersects`.
- A child whose clipped result is empty MUST be dropped from the output.
- `edge-mosaic` MUST raise if zero children were ever assigned to any parent.

## Stitching

- `edge-mosaic` MUST run one whole-layer coverage-clean pass over the clipped
  output, per `docs/reference/edge_stitch.md`, using the same fixed gap-closing
  width as `edge-extend`'s own merge stage (see `docs/reference/edge_extend.md`), not
  a per-feature-scoped pass.

## Outputs

- `edge-mosaic`'s final output MUST pass the hard gate in
  `docs/reference/shared.md` (no overlap, no gap at or below
  `SNAP_TOLERANCE`) before export. A wider leftover gap does not block
  export (see `docs/adr/0035`).
- `edge-mosaic` MUST export the final merged layer.
- `edge-mosaic` MUST also export an issues report alongside it, using the
  shared schema in `docs/reference/shared.md`, listing every unassigned
  child, every passthrough child (when `merge_columns` is truthy), and
  every leftover gap wider than `SNAP_TOLERANCE`, so a human can audit what
  didn't make it into the output or what may need review.
- For an `unassigned` row, `unit_a` MUST hold the child's own fid and
  `source_file` MUST record its origin file; parent id and reason fields
  MUST be null, since `edge-mosaic` has no per-group failure concept. For a
  `passthrough` row (`merge_columns` truthy only), `unit_a` and
  `source_file` MUST be populated the same way, and `reason` MUST explain
  that the file was kept unclipped for lack of an overlapping parent; a
  passthrough child MUST NOT also appear as an `unassigned` row. For a
  `gap` row, `area_m2`, `max_width_m`, and `thinness_ratio` MUST be
  populated instead. A field that doesn't apply to a row's kind MUST be
  null.
- `edge-mosaic` MUST produce the issues report only when it has at least one
  row; when it would be empty, no file MUST be written (and a stale file
  from a previous run at that path MUST be removed).

## Configuration (`api.edge_mosaic.mosaic()` / CLI)

- `edge-mosaic` MUST accept one or more child files and exactly one parent/clip
  file per call. The CLI additionally accepts `--input` (repeatable and
  comma-separable) alongside the glob-capable `INPUT_FILE` positional, both
  usable together, matching `edge-clip`'s own `--input` idiom.
- With a single child file, the output path MUST default to that input
  path with a `_mosaicked` suffix. With multiple child files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `edge-mosaic` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `edge-clip`, `edge-stitch`,
  `outputs`; any other value MUST raise `ValueError`. `step` MUST be `None`
  whenever more than one `input_paths` file is given; any other value MUST
  raise `ValueError` (see `docs/adr/0079`).
- `edge-mosaic` MAY accept `match_column`/`parent_match_column`/`child_match_column`
  to override spatial assignment with an exact code join (see
  `docs/reference/shared.md`, `docs/explanation/assign.md`).
- `edge-mosaic` MAY accept `merge_columns: list[str] | bool = False` (CLI:
  `--merge`, a boolean-or-value flag): `False` (default) copies no parent
  columns and drops a fully unmatched children file; `True` (bare
  `--merge`) copies every parent column (excluding `fid`/`geom`) onto
  every matched child and keeps a fully unmatched children file's own
  geometry unclipped in the output instead; a list (`--merge
  iso_3,adm0_name`) narrows the copied columns to just those, with
  passthrough still on. There is no way to enable one behavior without the
  other (see `docs/reference/shared.md`, `docs/adr/0077`,
  `docs/adr/0078`, `docs/adr/0079`).
