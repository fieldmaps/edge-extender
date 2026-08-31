# 0095: `edge-stitch`/`edge-match`/`edge-mosaic` gain opt-in `schema-fill` composition

## Status

Accepted.

## Context

Before this change, getting a merged, depth-stamped, schema-filled output
required two fully separate calls: `edge-match`/`edge-mosaic`/`edge-stitch`
to produce the merged layer, then a manual `schema-fill` call on its
output. There was no way to get both in one invocation.

`core.edge_stitch`, `core.edge_match`, and `core.edge_mosaic` are held to
"neutral leaf, MUST NOT depend on any tool package" (`docs/reference/
shared.md`); granting them a `core.schema_fill`/`core.schema_map`
dependency at that layer would break their reusability on schema-agnostic
polygon data, since `core.assign`/`core.edge_clip`/`core.edge_stitch`
(edge-match's and edge-mosaic's own reused primitives) know nothing about
admin hierarchies. The `api` layer has no such restriction, only "MUST NOT
depend on the CLI," so composition belongs there instead.

## Decision

A new private module, `topo_tools/api/_schema_fill_compose.py` (leading
underscore, matching `core/schema_map/_levels.py`'s own not-a-public-tool
convention), provides two functions:

- `validate_fill_flags(*, fill_schema, target_schema_path)`: raises
  `ValueError` if `target_schema_path` is given without `fill_schema`,
  named and shaped after `validate_merge_flags`'s own precedent.
- `apply_optional_fill(conn, name, table, *, requested, target_schema_path,
  depth_column, debug)`: a no-op unless `requested`. Otherwise: raises
  `ValueError` if `depth_column` already exists on `table` (a new guard,
  needed because `--merge --parent-include` can carry a parent's own
  `adm_lvl`-shaped column onto every child, which would otherwise surface
  as an opaque duplicate-column binder error deep in generated SQL);
  detects levels and loads the target schema (default: the bundled generic
  schema); then renames `table` to `{name}_fill_01`, calls
  `core.schema_fill._02_fill.main()` directly (`_01_inputs`/`_03_outputs`
  are file-I/O wrappers, unneeded here since the table is already loaded
  and the caller's own outputs stage does the export), writing
  `{name}_fill_02`, then renames that back to `table`. This is the same
  rename-swap idiom `_match_multi_file()`'s/`_mosaic_multi_file()`'s own
  accumulator folds already use. Under `--debug`, `{name}_fill_01` (the
  pre-fill snapshot) and the canonical output table (post-fill) both
  survive; there is no separately-named surviving `{name}_fill_02`, it
  *is* `table` again after the swap.

`stitch()`/`match()`/`mosaic()` each gain `fill_schema: bool = False`,
`target_schema_path: str | Path | None = None`, `depth_column: str =
"adm_lvl"`, call `validate_fill_flags()` near their existing
`validate_merge_flags()` call, and invoke `apply_optional_fill()`
immediately before their own final `outputs.main()` call. `match()` and
`mosaic()` each have two insertion points, since each has both a
single-file step loop and a separate `_match_multi_file()`/
`_mosaic_multi_file()` helper that calls `outputs.main()` directly for the
multi-file combine path; both insertion points fill the same table name
(`{name}_05` for edge-match, `{name}_04` for edge-mosaic, `{name}_02` for
edge-stitch) right after their own stitch stage. Fill only touches
attribute columns, never `fid`/`parent_fid`/`geom`/`source_file`, so
running it before `outputs.main()`'s topology validation and issues-report
building doesn't affect either.

The CLI gains a shared `_FILL_OPTIONS`/`_add_fill_options` decorator group,
mirroring `_MERGE_OPTIONS`/`_add_merge_options`: `--fill-schema` (the gate)
plus unprefixed `--target-schema`/`--depth-column`, matching `--merge`'s
own convention of not prefixing its narrowing flags (`--parent-include`,
not `--merge-parent-include`) and reusing `dissolve`'s/`schema-fill`'s own
exact flag names for the same concepts.

`fill_schema` and `merge` are independently gated and compose freely.
They are conceptually complementary, though: `merge`'s own
`fill_unmatched_parents()` (`docs/adr/0083`) fills a *geometry-coverage*
gap, a parent with zero matched children, by keeping its own unclipped
geometry in the output; `fill_schema` fills a *schema-depth* gap, a row
whose admin-hierarchy columns don't reach as deep as some other row's, by
cascading each column family down to the row's own real depth. No flag
rename was made to make this pairing more visible; the parallel is
documented instead (see `docs/explanation/edge_match.md`,
`docs/explanation/edge_mosaic.md`).

## Consequences

A caller can now get a merged, depth-stamped, schema-filled output in one
`edge-stitch`/`edge-match`/`edge-mosaic` call, opt-in via `--fill-schema`.
`core.edge_stitch`/`core.edge_match`/`core.edge_mosaic` are unchanged; no
`.importlinter` contract changes were needed, confirmed by `lint-imports`
after the change. `fill_schema` without any admin-hierarchy columns on the
merged table raises the same `ValueError` `schema-fill`'s own
`detect_levels()` already raises for that case, propagated unchanged.
