# 0044: Combine multi-file input with one query, not a table per file

## Status

Accepted.

## Context

Profiling the newly-added multi-file `stitch` input role (`--debug` run
against the 111-file, ~893MB `tmp/clipped` portolan batch) showed the
input-combine step spiking RSS from ~2.4GB (after loading all 111 files)
to a peak of 6.29GB in one query, settling at ~4.96GB once scratch tables
were dropped.

The cause was shared by `core/stitch/_01_inputs.py`'s new loader and the
pre-existing `core/assign/_inputs.py::load_children()` (`mosaic`'s own
multi-child-file path): both read every input file into its own fully
materialized scratch table via `core.io.read_and_reproject()` first, then
issued a second query to `UNION ALL BY NAME` all of them into a fresh
combined table, then dropped the scratch tables. For the duration of that
second query, both the N scratch tables and the new combined table exist
in memory at once, roughly doubling peak RSS versus a single streaming
pass over the same data.

`clip`'s own multi-file children role is unaffected: per ADR-0023 it
already learned this exact lesson and calls `load_children()` with one
file at a time inside its per-`parent_fid` loop, never combining N files
into one table at once.

## Decision

`core/io.py::read_and_reproject()`'s SQL-generation half (schema
introspection via `DESCRIBE`, reserved-column rename, geometry-transform
expression) is split out into a new function,
`reproject_select_sql(conn, path) -> str`, returning the `SELECT ... FROM
(...)` text unexecuted instead of running it into a table.
`read_and_reproject()` becomes a thin wrapper: `CREATE OR REPLACE TABLE
"{name}_01" AS {reproject_select_sql(conn, path)}`, generating
byte-identical SQL to before for every single-file caller (`extend`,
`clip`, `assign.load_parent`, single-file `stitch`, `change`).

Both `load_children()` and stitch's multi-file `_01_inputs.main()` now
build one `CREATE TABLE ... AS SELECT ... FROM (subquery UNION ALL BY
NAME subquery UNION ALL BY NAME ...)` from N `reproject_select_sql()`
calls, with the global `row_number()` fid reassignment wrapped around the
whole union as before. No scratch tables are created or dropped; DuckDB
reads, transforms, and unions all N files in one query plan.

## Consequences

One materialization instead of two for the combine step, for both
`mosaic`'s multi-child-file path and `stitch`'s multi-file input role.
Output is identical (same rows, same `source_file` tagging where
applicable) since the transform SQL itself didn't change, only when it
gets executed. `clip`'s multi-file role, already unaffected by the
original problem (ADR-0023), is untouched by this change too.
