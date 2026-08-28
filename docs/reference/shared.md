# shared

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention. Rules here apply
across more than one tool; a tool's own file references this one by name
instead of repeating them.

## Import boundaries (mechanically enforced)

- Core tool logic MUST NOT depend on the command-line interface.
- The public API layer MUST NOT depend on the command-line interface.
- The `edge-match` tool MAY reuse `edge-extend`'s logic; `edge-extend` MUST NOT depend on
  `edge-match`.
- The `edge-mosaic` tool MUST NOT depend on `edge-extend` or `edge-match`, and neither
  MUST depend on `edge-mosaic` (see `docs/explanation/edge_mosaic.md`).
- The `topo-clean` tool MAY reuse `topo-detect`'s logic; `topo-detect` MUST NOT depend on
  `topo-clean` (see `docs/explanation/topo_detect.md`, `docs/adr/0028`).
- The shared constants, coverage-validation, file I/O, database-connection,
  units, assign, edge-clip, topo-detect, and edge-stitch helpers MUST NOT depend on any
  of the five tool packages (`edge-extend`, `edge-match`, `topo-clean`, `change`,
  `edge-mosaic`); they are leaf building blocks usable by all of them.
- The `schema-crosswalk` tool MAY reuse `schema-map`'s and `schema-refactor`'s logic directly;
  neither `schema-map` nor `schema-refactor` MUST depend on `schema-crosswalk`, or on each
  other (see `docs/explanation/schema_crosswalk.md`).
- `schema-fill` and `dissolve` MAY both depend on `schema-map`'s
  target-schema/level-detection helpers (`core/schema_map/_levels.py`);
  `schema-map` MUST NOT depend on either (see `docs/adr/0075`,
  `docs/adr/0092`).

## Coverage-topology checks

- The shared overlap/mismatched-edge check MUST NOT be treated as a gap
  check: it reports "no violations" both when a real, fully-enclosed gap
  exists with no overlaps, and when the data has collapsed to nothing.
- The shared gap check MUST detect fully-enclosed interior holes only, in
  the union of a layer's geometries.
- The shared gap check MAY be scoped to a maximum hole width: given one, it
  MUST report only holes at or below that width, treating a wider hole as a
  possible legitimate absence rather than a defect. Omitting the width MUST
  preserve the unscoped, any-size-hole behavior.

## Common settings

Every tool's public API function takes these in addition to its own
tool-specific settings (see the tool's own file for those):

- `tmp_dir`: intermediate DuckDB + Parquet location; MUST default to a
  fresh temporary directory when unset, and MUST be cleaned up after the
  call unless `debug` is set.
- `threads`: DuckDB thread count; unset MUST defer to DuckDB's own
  default.
- `overwrite`: whether to overwrite an existing output path; MUST default
  to `True`, logging `"overwriting existing output: {path}"` when it
  does; passing `False` (CLI: `--overwrite=false`) MUST raise
  `FileExistsError` instead if any output path already exists. Every
  `api.*()` function MUST route this check through
  `core.io.check_overwrite()` rather than an inline check, so the
  behavior stays in one place (see `docs/adr/0063`).
- `debug`: MUST keep intermediate tables, export all of them to Parquet,
  and log timing + memory delta per query.
- `step`: if given, MUST run only the one named stage; any value outside
  that tool's own stage names MUST raise `ValueError`.

A read-role file argument (children, parent/clip, old/new) MAY be an
`http://`/`https://` URL to a `.parquet` file, resolved via
`core.io.resolve_input_path()`/`input_basename()` (see `docs/adr/0043`);
behavior for a non-parquet remote URL is unverified. An output-role
argument (`output_path`, `issues_path`, `overlay_path`) MUST always be a
local filesystem path.

No module-level `argparse`/env parsing exists anywhere; settings flow in
as plain keyword arguments on each tool's own `api.*()` function, and the
CLI maps flags/env vars onto those same kwargs 1:1.

## Hard gates at each tool's output stage

- `edge-extend` MUST raise if its final output has any overlap or any gap of any
  size: it has no parent/clip layer, so any gap is unambiguously a defect
  in its own coverage (see `docs/adr/0035`).
- `edge-match` and `edge-mosaic` MUST raise if their final output has any overlap, or
  any gap at or below `SNAP_TOLERANCE`. A wider gap MUST NOT raise: it may
  be a legitimate hole in the parent/clip layer's own shape (e.g. one
  country fully enclosing another), not a coverage defect (see
  `docs/adr/0035`). Any such gap MUST still be logged as a warning and
  recorded in the issues report described in each tool's own file.
- `topo-clean` MUST raise if its final output has any overlap, or any unfilled
  gap at or below the `gap_maximum_width` actually used for that run (see
  `docs/adr/0037`). It MUST NOT raise over a gap wider than that: gaps
  above the requested fill width may legitimately remain by design and
  are only logged.
- `edge-stitch` MUST raise if its final output has any overlap, or any gap at
  or below `SNAP_TOLERANCE` (see `docs/adr/0038`). It MUST NOT raise over
  a wider gap, but MUST log a warning and record it in the issues report
  described in `docs/reference/edge_stitch.md`.
- `edge-clip` performs no topology hard gate at all: it clips a child to its
  assigned parent's geometry one `parent_fid` at a time and does not
  itself validate whole-layer coverage. It MAY still produce an issues
  report (a `clip-empty` row for any child whose clip result was empty,
  plus `code-mismatch`/`code-fallback` rows when a match column is
  supplied, see below).
- `change` performs no topology hard gate at all; it is a read-only
  comparison between two inputs, not a fix.
- `topo-detect` performs no topology hard gate at all; it is a read-only
  inspection, not a fix.

## Issues report schema

`topo-clean`, `edge-match`, `edge-mosaic`, `edge-clip`, and `edge-stitch` each MAY
produce an issues report alongside their main output, sharing one column
schema: `key`, `kind`, `area_m2`, `max_width_m`, `thinness_ratio`,
`unit_a`, `unit_b`, `parent_fid`, `reason`, `unit_a_area_change_m2`,
`unit_b_area_change_m2`, `filled_area_m2`, `fixed`, `source_file`, `geom`.
A tool MUST leave any column inapplicable to a given row's `kind` as null.
`unit_a` MUST record whichever single fid is primarily associated with the
row, for any kind that has one (a dropped child, one side of an overlap,
etc.); `unit_b` MUST be used only where a second fid is meaningfully
involved (e.g. the other side of an overlap). `edge-match` MUST populate
`source_file` with the row's originating child file, shortened to its
parent directory plus filename (never the full input path), for every
kind that has one (`unassigned`, `dropped_group`, `clip-empty`,
`passthrough`), null only for `gap` (see `docs/adr/0084`,
`docs/adr/0087`).

None of `edge-match`/`edge-mosaic`/`edge-clip`/`edge-stitch`'s *main*
output carries a `source_file` column at all, even though every one of
them tags it internally on the child table: it exists only to let
`assign-one` group a file's children for its per-file majority vote (see
`docs/explanation/assign.md`), not as a user-facing column, and each
tool's outputs stage strips it before export (see `docs/adr/0087`).
`topo-clean`'s issues report keeps a `source_file` column for schema
compatibility, always null (it's a single-layer tool with no per-child
origin file).

`edge-match`, `edge-mosaic`, and `edge-clip` all share a `kind='clip-empty'`
row for any child whose clip intersection with its assigned parent came
back empty (see `docs/adr/0082`): `unit_a` MUST hold the child's fid,
`parent_fid` its assigned parent's fid, `reason` MUST explain the
intersection was empty. `edge-mosaic` and `edge-match` both additionally
have a `kind='gap-fill'` row (see `docs/reference/edge_mosaic.md`,
`docs/reference/edge_match.md`) for a parent matched by zero children,
kept unclipped in the output when `merge` is set: `parent_fid` MUST hold
the gap-filled parent's fid, `unit_a` and `source_file` MUST be null (see
`docs/adr/0083`, `docs/adr/0088`).

A tool MUST NOT write an issues file at all when the run produced zero
issues rows; if a file already exists at the destination path from a
previous run, it MUST be deleted rather than left in place.

## Code-based assignment override

`edge-match`, `edge-mosaic`, and standalone `edge-clip` all MAY accept a `match_column`
name (same column on both layers) or a `parent_match_column`/
`child_match_column` pair (different names), mutually exclusive with each
other; supplying only one of the pair MUST raise `ValueError`. When given,
`core/assign`'s exact code join wins over the
default spatial-overlap assignment wherever a code match exists, even when
it disagrees with the spatial result, and falls back to the spatial result
when a child's (or, for `assign-one`, a file's) code has no
overlapping-parent match at all (see `docs/adr/0045`,
`docs/explanation/assign.md`). Both outcomes MUST be recorded as issues
rows, reusing the schema above:

- `kind='code-mismatch'`: the code match won but disagreed with the spatial
  result. `unit_a` MUST hold the child's own fid, `parent_fid` the code
  match's parent.
- `kind='code-fallback'`: no code match existed; the spatial result was
  used instead. `unit_a` and `parent_fid` MUST be populated the same way.

This gives standalone `edge-clip` its only issues-report capability: it produces
one only when `match_column`/`parent_match_column`/`child_match_column` is
supplied and it yields at least one row (see `docs/reference/edge_clip.md`).

## Parent-column carry-forward

`edge-match`, `edge-mosaic`, and standalone `edge-clip` all MAY copy named
parent-layer columns onto every matched child. Names are always
caller-specified, never inferred from either layer's schema (see
`docs/adr/0077`). A name colliding with `core.assign`'s own reserved
columns (`child_fid`, `parent_fid`, `assignment_method`, `spatial_agrees`)
MUST raise `ValueError`; a name colliding with the child layer's own
schema MUST also raise `ValueError` (an explicit pre-check, not left to
the SQL layer to reject on its own, see `docs/adr/0077`).

Standalone `edge-clip` exposes this as a plain `carry_columns` list (CLI:
repeatable, comma-splittable `--carry-column`), attribute-carrying only,
with no gap-fill concept of its own (`edge-clip` is a strict 1:1
primitive, see `docs/reference/edge_clip.md`).

`edge-mosaic` and `edge-match` both expose this as a plain boolean
`merge: bool = False` (CLI: `--merge`), coupled with two passthrough
mechanisms rather than independent of them: `False` (omitted) turns both
off; `True` carries every parent column (excluding `fid`/`geom`) onto
every matched child, keeps a parent matched by zero children unclipped in
the output using its own geometry (`kind='gap-fill'`), and keeps a whole
unmatched child file unclipped in the output using its own geometry
(`kind='passthrough'`). `parent_include`/`parent_exclude`/
`child_include`/`child_exclude` (CLI: `--parent-include`/
`--parent-exclude`/`--child-include`/`--child-exclude`) narrow which
parent/child columns survive; `prefer` (CLI: `--prefer [parent|child]`)
auto-resolves a real parent/child column-name collision instead of
raising. All five require `merge`; the four narrowing flags are each
mutually exclusive with their own pair, and mutually exclusive with
`prefer` (see `docs/adr/0079`, `docs/adr/0083`, `docs/adr/0088`). A child
that never matched any parent (dropped as `unassigned`) never gains
carried columns through a join; a gap-filled parent's own row carries
them directly, since the row is the parent itself, not a joined child
(see `docs/reference/edge_mosaic.md`).

The two tools' child-passthrough implementations differ, since their
pipelines do: `edge-mosaic`'s passthrough geometry is already a finished,
validated `edge_extend()` output, unioned in directly. `edge-match`'s
passthrough groups every zero-overlap child (whole file under
`assign-one`, individual child under `--multi-parent`'s `assign-many`,
see `docs/explanation/assign.md`) into one orphan group of its own and
extends it fresh, alone, with zero neighboring-parent context and no
majority/plurality vote to catch a bad extension, a materially weaker
safety profile than `edge-mosaic`'s (see `docs/adr/0081`). Parent
gap-fill has no such asymmetry: both tools call the same shared
`core.assign.fill_unmatched_parents()` helper (see `docs/adr/0088`).
