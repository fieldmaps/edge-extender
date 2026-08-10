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

- `extend`, `match`, and `mosaic` MUST raise if their final output has any
  overlap or any gap.
- `clean` MUST raise if its final output has any overlap. It MUST NOT raise
  over an unfilled gap: gaps may legitimately remain by design and are
  only logged.
- `stitch` MUST raise if its final output has any overlap. It MUST NOT
  raise over any gap (see `docs/adr/0027`).
- `change` performs no topology hard gate at all; it is a read-only
  comparison between two inputs, not a fix.
- `detect` performs no topology hard gate at all; it is a read-only
  inspection, not a fix.
