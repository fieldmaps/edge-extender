# shared

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention. Rules here apply
across more than one tool; a tool's own file references this one by name
instead of repeating them.

## Import boundaries (mechanically enforced)

- Core tool logic MUST NOT depend on the command-line interface.
- The public API layer MUST NOT depend on the command-line interface.
- The `match` tool MAY reuse `extend`'s logic; `extend` MUST NOT depend on
  `match`.
- The `change` tool MAY reuse `extend`'s logic; `extend` MUST NOT depend on
  `change`.
- The `mosaic` tool MUST NOT depend on `extend` or `match`, and neither
  MUST depend on `mosaic` (see `docs/explanation/mosaic.md`).
- The `clean` tool MAY reuse `detect`'s logic; `detect` MUST NOT depend on
  `clean` (see `docs/explanation/detect.md`, `docs/adr/0028`).
- The shared constants, coverage-validation, file I/O, database-connection,
  units, assign, clip, detect, and stitch helpers MUST NOT depend on any
  of the five tool packages (`extend`, `match`, `clean`, `change`,
  `mosaic`); they are leaf building blocks usable by all of them.

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
- `overwrite`: whether to overwrite an existing output path.
- `debug`: MUST keep intermediate tables, export all of them to Parquet,
  and log timing + memory delta per query.
- `step`: if given, MUST run only the one named stage; any value outside
  that tool's own stage names MUST raise `ValueError`.

No module-level `argparse`/env parsing exists anywhere; settings flow in
as plain keyword arguments on each tool's own `api.*()` function, and the
CLI maps flags/env vars onto those same kwargs 1:1.

## Hard gates at each tool's output stage

- `extend` MUST raise if its final output has any overlap or any gap of any
  size: it has no parent/clip layer, so any gap is unambiguously a defect
  in its own coverage (see `docs/adr/0035`).
- `match` and `mosaic` MUST raise if their final output has any overlap, or
  any gap at or below `SNAP_TOLERANCE`. A wider gap MUST NOT raise: it may
  be a legitimate hole in the parent/clip layer's own shape (e.g. one
  country fully enclosing another), not a coverage defect (see
  `docs/adr/0035`). Any such gap MUST still be logged as a warning and
  recorded in the issues report described in each tool's own file.
- `clean` MUST raise if its final output has any overlap, or any unfilled
  gap at or below the `gap_maximum_width` actually used for that run (see
  `docs/adr/0037`). It MUST NOT raise over a gap wider than that: gaps
  above the requested fill width may legitimately remain by design and
  are only logged.
- `stitch` MUST raise if its final output has any overlap. It MUST NOT
  raise over any gap (see `docs/adr/0027`), but MUST log a warning and
  record it in the issues report described in `docs/reference/stitch.md`
  if a gap wider than `SNAP_TOLERANCE` remains.
- `clip` performs no topology hard gate at all: it clips a child to its
  assigned parent's geometry one `parent_fid` at a time and does not
  itself validate whole-layer coverage.
- `change` performs no topology hard gate at all; it is a read-only
  comparison between two inputs, not a fix.
- `detect` performs no topology hard gate at all; it is a read-only
  inspection, not a fix.

## Issues report schema

`clean`, `match`, `mosaic`, and `stitch` each MAY produce an issues report
alongside their main output, sharing one column schema: `key`, `kind`,
`area_m2`, `max_width_m`, `thinness_ratio`, `unit_a`, `unit_b`,
`parent_fid`, `reason`, `unit_a_area_change_m2`, `unit_b_area_change_m2`,
`filled_area_m2`, `fixed`, `source_file`, `geom`. A tool MUST leave any
column inapplicable to a given row's `kind` as null. `unit_a` MUST record
whichever single fid is primarily associated with the row, for any kind
that has one (a dropped child, one side of an overlap, etc.); `unit_b`
MUST be used only where a second fid is meaningfully involved (e.g. the
other side of an overlap).

A tool MUST NOT write an issues file at all when the run produced zero
issues rows; if a file already exists at the destination path from a
previous run, it MUST be deleted rather than left in place.
