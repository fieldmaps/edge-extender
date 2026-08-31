# edge-match

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md`/`docs/reference/edge_extend.md` for rules `edge-match` shares with other
tools.

## Inputs

- `edge-match` MUST coverage-clean the child layer, the same way
  `edge-extend`'s own inputs stage does (see `docs/reference/edge_extend.md`),
  and MUST load the parent/clip layer raw, uncleaned, the same way
  `edge-mosaic`'s parent load does (see `docs/adr/0086`).
- The child role MAY span multiple files (e.g. one raw admin boundary file
  per country), combined internally. The parent/clip layer MUST remain a
  single file.
- The main output MUST NOT carry a `source_file` column; it is an
  internal working column only, used by `assign-one`'s per-file grouping
  (see `docs/explanation/assign.md`), not exported. The issues report MAY
  carry `source_file`, shortened to its parent directory plus filename
  (e.g. `sen/adm2.parquet`), never the full input path (see
  `docs/adr/0087`).

## Assigning children to parents

- By default, `edge-match` MUST assign every child from the input file to a
  single parent polygon shared by the whole file, chosen by majority vote
  of that file's children (`assign-one`, see `docs/explanation/assign.md`);
  a tie between two candidate parents MUST be broken by the lower parent
  id. Once the file has a winner, every child in it MUST be assigned to
  that parent unconditionally, including a child with zero individual
  overlap with it; such a child is not dropped here, but MAY still drop
  later at clip time if its extended geometry never reaches the parent
  (see Clipping), reported as a `kind='clip-empty'` issue row.
- When `--multi-parent` (`multi_parent=True`) is given, `edge-match` MUST
  instead assign each child polygon independently to the single parent
  polygon it shares the largest overlapping area with (`assign-many`), so
  one input file's children MAY scatter across many different parents.
  Use this only when children genuinely belong to different parents, e.g.
  a poorly-digitized admin4 layer fitting into many admin3 units.
- Under `assign-one` (default), a whole input file with no child
  overlapping any parent at all MUST be dropped, not treated as fatal, and
  `edge-match` MUST log a warning naming its children. Under `assign-many`
  (`--multi-parent`), an individual child with no overlap with any parent
  MUST be dropped the same way. Either case, unless `merge` is set (see
  Configuration), in which case the dropped child(ren) are instead
  grouped into one orphan group of their own and extended together (see
  "Extending each group"), kept unclipped in the output. Either case MUST
  also be recorded in the issues report described under Outputs.
- A parent matched by zero children MUST be dropped, unless `merge` is
  set (see Configuration), in which case that parent's own geometry and
  attributes are kept unclipped in the output instead. This case MUST
  also be recorded in the issues report described under Outputs.

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

- `edge-match` MUST clip every real group's reassembled, extended output to its
  own `parent_fid`'s geometry, per `docs/reference/edge_clip.md`, one distinct
  `parent_fid` at a time, each in its own spawned OS subprocess. The orphan
  group (`merge` set only) MUST NOT be clipped; it has no parent to clip
  against. A parent matched by zero children (`merge` set only) MUST be
  appended to the clipped result afterward, via its own unclipped
  geometry, before stitching.
- Unlike a failed group's extension, `edge-match` MUST raise immediately if any
  real `parent_fid`'s clip subprocess fails, aborting the whole run rather than
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
  child belonging to a dropped group, every child dropped for an empty
  clip intersection, every passthrough child and gap-filled parent
  (`merge` set only), and every leftover gap wider than `SNAP_TOLERANCE`,
  so a human can audit what didn't make it into the output or what may
  need review.
- For an `unassigned`/`dropped_group`/`clip-empty`/`passthrough` row,
  `source_file` MUST record the child's own origin file as a
  parent-directory-plus-filename (not the full path). For a `gap-fill` or
  `gap` row, `source_file` MUST be null, since neither has a single
  originating child file.
- For an `unassigned`/`dropped_group`/`clip-empty`/`passthrough` row,
  `unit_a` MUST hold the child's own fid; for a `dropped_group` row,
  `parent_fid` and `reason` MUST record the group's assigned parent and
  drop reason. For a `clip-empty` row, `parent_fid` MUST hold the child's
  assigned parent's fid and `reason` MUST explain that the clip
  intersection came back empty. For a `passthrough` row, `reason` MUST
  explain that the child had no overlapping parent and was extended alone
  and kept unclipped in the output; a passthrough child MUST NOT also
  appear as an `unassigned` row. For a `gap-fill` row, `parent_fid` MUST
  hold the gap-filled parent's fid and `reason` MUST explain that the
  parent had no matched children and was kept unclipped in the output;
  `unit_a` MUST be null, since the row is the parent itself, not a child.
  For a `gap` row, `area_m2`, `max_width_m`, and `thinness_ratio` MUST be
  populated instead. A field that doesn't apply to a row's kind MUST be
  null.
- `edge-match` MUST produce the issues report only when it has at least one
  row; when it would be empty, no file MUST be written (and a stale file
  from a previous run at that path MUST be removed).

## Configuration (`api.edge_match.match()` / CLI)

- `edge-match` MUST accept one or more child files and exactly one parent/clip
  file per call. The CLI additionally accepts `--input` (repeatable and
  comma-separable) alongside the glob-capable `INPUT_FILE` positional, both
  usable together, matching `edge-mosaic`'s own `--input` idiom.
- With a single child file, the output path MUST default to that input
  path with a `_matched` suffix. With multiple child files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `edge-match` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `assign`, `groups`, `edge-clip`,
  `edge-stitch`, `outputs`; any other value MUST raise `ValueError`. `step`
  MUST be `None` whenever more than one child file is given; any other
  value MUST raise `ValueError` (see `docs/adr/0084`).
- `edge-match` MAY accept `match_column`/`parent_match_column`/`child_match_column`
  to override spatial assignment with an exact code join (see
  `docs/reference/shared.md`, `docs/explanation/assign.md`).
- `edge-match` MAY accept `multi_parent: bool = False` (CLI:
  `--multi-parent`): `False` (default) assigns the whole input file to one
  majority-vote parent (`assign-one`); `True` assigns each child
  independently to whichever parent it overlaps most (`assign-many`), for
  files whose children genuinely scatter across multiple parents (see
  `docs/explanation/assign.md`, `docs/adr/0082`). `multi_parent` MUST be
  `False` whenever more than one child file is given; any other value MUST
  raise `ValueError` (see `docs/adr/0084`).
- `edge-match` MAY accept `merge: bool = False` (CLI: `--merge`, a plain
  boolean flag): `False` (default) copies no parent columns and drops
  both an unmatched child and a zero-children parent; `True` copies every
  parent column (excluding `fid`/`geom`) onto every matched child, keeps
  an unmatched child's own extended geometry in the output unclipped
  (`kind='passthrough'`), and keeps a zero-children parent's own geometry
  in the output unclipped (`kind='gap-fill'`). There is no way to enable
  one behavior without the other.
- With `merge` set, `edge-match` MAY additionally accept
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
- With `merge` set, `edge-match` MAY additionally accept `prefer:
  "parent" | "child" | None = None` (CLI: `--prefer`) to auto-resolve a
  real parent/child column-name collision: `"parent"` keeps the parent's
  column and drops the child's, `"child"` does the reverse. Omitting
  `prefer` (the default) preserves raising `ValueError` on a real
  collision. `prefer` MUST raise `ValueError` if given without `merge`,
  or combined with any of `parent_include`/`parent_exclude`/
  `child_include`/`child_exclude` (see `docs/reference/shared.md`,
  `docs/adr/0077`, `docs/adr/0081`, `docs/adr/0088`).
- `edge-match` MAY opt into cascading admin-hierarchy columns via
  `fill_schema`/`--fill-schema`, right after stitching and before export
  (both the single-file step loop and the multi-file combine path).
  `target_schema_path`/`--target-schema` (default: the bundled generic
  schema) and `depth_column`/`--depth-column` (default `adm_lvl`) narrow
  it; both MUST raise `ValueError` if given without `fill_schema=True`.
  `edge-match` MUST raise `ValueError` if `depth_column` already names an
  existing column when `fill_schema` is set. `fill_schema` is independent
  of `merge`: it fills a per-row schema-depth gap left by the input data
  itself, while `merge`'s own gap-fill (`fill_unmatched_parents()`, see
  `docs/adr/0083`) fills a per-parent geometry-coverage gap left by the
  match; the two compose freely (see `docs/adr/0095`).
