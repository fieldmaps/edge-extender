# 0094: Multi-file merges sort inputs by column count descending

## Status

Accepted.

## Context

`edge-stitch`, `edge-match`, and `edge-mosaic` each combine multiple input
files into one table via `UNION ALL BY NAME` (`edge-stitch`'s
`_01_inputs.py`) or a rename-swap fold built on the same operator
(`edge-match`'s and `edge-mosaic`'s `_fold()`, used by
`_match_multi_file()`/`_mosaic_multi_file()`). Direct DuckDB testing
confirmed `UNION ALL BY NAME` takes its column order from the **leftmost**
operand for every shared column name, appending any newly-introduced name
in first-encountered order. None of the three call sites picked that
leftmost file deliberately, so the output's column order was an accident of
whatever order the caller happened to pass files in (CLI glob expansion,
`--input` flag order, directory listing order), not something reproducible
across runs.

## Decision

Sort the file list by column count descending, tie-broken by filename, at
all three call sites before unioning/folding: `core.io.sort_paths_by_column_count_desc()`.
This is a pure structural proxy (more columns generally means a deeper admin
hierarchy in this domain) rather than a schema-aware ordering, so it needs
no `.importlinter` changes and works identically whether or not a
`schema-map` target schema is even in play.

## Consequences

Output column order is now deterministic regardless of caller-supplied file
order (CLI glob expansion, `--input` order), verified by a regression test
per call site that runs the same two fixture files in both orders and
asserts identical output columns. It does not guarantee "the file with the
deepest admin schema wins" in a contrived case where a shallower file has
more non-admin columns; it only guarantees full determinism either way.
