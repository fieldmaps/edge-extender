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
- The main output MUST NOT carry a `source_file` column; it is an
  internal working column only, used by `assign-one`'s per-file grouping
  (see `docs/explanation/assign.md`), not exported. The issues report MAY
  carry `source_file`, shortened to its parent directory plus filename
  (e.g. `sen/adm2.parquet`), never the full input path (see
  `docs/adr/0087`).

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
- Once a file has a winning parent, every child in that file MUST be
  assigned to it unconditionally, including a child with zero individual
  overlap with the winner; such a child is not dropped at assign time (see
  `docs/explanation/assign.md`). A whole file with no child overlapping
  any parent at all MUST be dropped, not treated as fatal, and
  `edge-mosaic` MUST log a warning naming its children, unless `merge`
  is set (see Configuration), in which case that file's own
  already-extended geometry is instead kept unclipped in the output.
- A parent matched by zero children MUST be dropped, unless `merge`
  is set (see Configuration), in which case that parent's own geometry
  and attributes are kept unclipped in the output instead. Either case
  MUST also be recorded in the issues report described under Outputs.

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
- A child whose clipped result is empty MUST be dropped from the output,
  not treated as fatal, and MUST be recorded in the issues report as a
  `kind='clip-empty'` row (see Outputs).
- `edge-mosaic` MUST raise if zero children were ever assigned to any parent,
  unless `merge` gap-filled at least one parent or kept at least one
  unmatched child file as passthrough (see Configuration).

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
  shared schema in `docs/reference/shared.md`, listing every child dropped
  for an empty clip intersection, every unassigned/passthrough child file,
  every gap-filled/passthrough parent (when `merge` is set), and every
  leftover gap wider than `SNAP_TOLERANCE`, so a human can audit what
  didn't make it into the output or what may need review.
- Without `merge`, a whole unmatched child file MUST appear as an
  `unassigned` row: `unit_a` MUST hold the child's own fid and
  `source_file` MUST record its origin file as a parent-directory-plus-
  filename (not the full path); parent id and reason fields MUST be null.
  With `merge` set, that file's children MUST instead appear as
  `passthrough` rows (same `unit_a`/`source_file` shape, `reason` null),
  and MUST NOT also appear as `unassigned`. For a `clip-empty` row,
  `unit_a` MUST hold the child's fid, `parent_fid` MUST hold its assigned
  parent's fid, `source_file` MUST record its origin file the same
  shortened way, and `reason` MUST explain that the clip intersection
  came back empty. For a `gap-fill` row (`merge` set only), `parent_fid`
  MUST hold the gap-filled parent's fid and `reason` MUST explain that the
  parent had no matched children and was kept unclipped in the output;
  `unit_a` and `source_file` MUST be null, since the row is the parent
  itself, not a child. For a `gap` row, `area_m2`, `max_width_m`, and
  `thinness_ratio` MUST be populated instead. A field that doesn't apply
  to a row's kind MUST be null.
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
- `edge-mosaic` MAY accept `merge: bool = False` (CLI: `--merge`, a plain
  boolean flag): `False` (default) copies no parent columns and drops
  both a zero-children parent and a whole unmatched child file; `True`
  copies every parent column (excluding `fid`/`geom`) onto every matched
  child, keeps a zero-children parent's own geometry unclipped in the
  output (`kind='gap-fill'`), and keeps a whole unmatched child file's own
  geometry unclipped in the output (`kind='passthrough'`). There is no
  way to enable one behavior without the other.
- With `merge` set, `edge-mosaic` MAY additionally accept
  `parent_include`/`parent_exclude` (CLI: `--parent-include`/
  `--parent-exclude`, each a comma-separated column list) to narrow which
  parent columns get copied onto matched children (default: every parent
  column except `fid`/`geom`), and `child_include`/`child_exclude` (CLI:
  `--child-include`/`--child-exclude`) to narrow which of the child's own
  columns survive in the output (default: every child column;
  `fid`/`geom`/`source_file` are always force-kept regardless). Each pair
  is mutually exclusive with itself; a parent-side flag MAY be combined
  with a child-side flag. All four MUST raise `ValueError` if given
  without `merge`.
- With `merge` set, `edge-mosaic` MAY additionally accept `prefer:
  "parent" | "child" | None = None` (CLI: `--prefer`) to auto-resolve a
  real parent/child column-name collision: `"parent"` keeps the parent's
  column and drops the child's, `"child"` does the reverse. Omitting
  `prefer` (the default) preserves raising `ValueError` on a real
  collision. `prefer` MUST raise `ValueError` if given without `merge`,
  or combined with any of `parent_include`/`parent_exclude`/
  `child_include`/`child_exclude` (see `docs/reference/shared.md`,
  `docs/adr/0077`, `docs/adr/0079`, `docs/adr/0083`, `docs/adr/0088`;
  supersedes the child-orphan passthrough of `docs/adr/0078`).
