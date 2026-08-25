# 0079: `edge-mosaic` adopts standalone `edge-clip`'s per-file loop; `--merge` replaces `--carry-column`/`--on-unmatched`

## Status

Accepted.

## Context

Standalone `edge-clip`'s multi-file mode (ADR-0022/0023/0024) exists to
batch many children files against one shared parent load without reloading
a large global parent (e.g. a ~730MB world adm0 file) per country.
`edge-mosaic` is the tool meant to own that global-build use case
(already-extended children, `assign-one`, attribute merging), so
`edge-clip` carrying its own multi-file mode duplicates a job `edge-mosaic`
should do instead (see ADR-0080).

But `edge-mosaic`'s own multi-file mode, before this ADR, loaded every
children file into one combined table (`load_children(conn, name, paths)`)
and ran a single `assign_one()` pass over the whole batch: exactly the
design ADR-0023 measured pushing process RSS to ~7.6GB and still climbing
(aborted) against the full 111-country portolan catalog, before
`edge-clip` was redesigned into its current per-file loop. `edge-mosaic`
could not take over `edge-clip`'s batching job without first fixing this.

Separately, `edge-mosaic`'s gap-fill passthrough (ADR-0078) and its
attribute carry-forward (`carry_columns`, ADR-0077) had accumulated as two
independent opt-ins (`--on-unmatched passthrough` / `--carry-column`), but
in practice a caller always wants both together or neither: a country kept
in the output via passthrough is far more useful with its parent
attributes populated too, and there's no real use case for wanting
gap-fill without any attribute enrichment. Two independently-toggled flags
also don't communicate that coupling, forcing a caller to learn and
combine them correctly by convention rather than by the API shape itself.

## Decision

1. **Per-file loop, ported from `edge-clip`'s ADR-0023/0024 pattern.** A new
   private `_mosaic_multi_file()` (`api/edge_mosaic.py`) loads the parent
   once into a pristine `{name}_parent_full` snapshot, calls
   `core.assign.prepare_parent_tiles()` once (ADR-0024's caching, reused
   as-is), then for each children file: restores `{name}_parent_01}` from
   the snapshot, loads just that file's children, assigns
   (`use_cached_tiles=True`), clips, and folds the result into a running
   accumulator. Used only when more than one `input_paths` is given;
   single-file calls keep the original direct stage loop unchanged.
2. **Mosaic-specific departures from `edge-clip`'s pattern**, needed
   because `edge-mosaic` has one combined output where `edge-clip` has one
   output per input file:
   - `stitch`/`outputs` cannot run per file (closing a seam between two
     files' clipped output needs both sides at once), so the loop only
     replaces `inputs`+`assign`+`clip`; `stitch`+`outputs` still run
     exactly once, after the loop, over the fully accumulated result.
   - Each iteration's clip result is folded into the accumulator
     immediately (`UNION ALL BY NAME`, seeded on the first file), never
     stashed until a final N-way union, which would reintroduce holding
     the whole batch in memory at once.
   - `load_children()` always resets `fid` to `row_number() OVER ()`
     starting at 1 for whatever it's given, so calling it once per file
     would collide every file's fids. A running `fid_offset`, applied via
     `UPDATE ... SET fid = fid + {fid_offset}` right after each
     `load_children()` call and before `assign_one()` runs, keeps `fid`
     globally unique for the whole run, not just at final export.
   - `{name}_child_01}`/`{name}_02_assign}` are accumulated too, not just
     the clip result/unassigned/passthrough tables, so a code-join's
     issue rows (`assign_issue_rows_sql`) can still join correctly against
     the whole run's children after the loop ends, and so
     passthrough/unassigned exclusion logic compares globally, not
     locally, unique fids.
   - Whole-file-unmatched (passthrough) detection simplifies to a
     per-iteration check (`{name}_02_assign}` has zero rows for this
     file), replacing the old whole-batch `source_file` set difference.
   - `core/edge_mosaic/_01_clip.py::main()` gains `raise_if_empty: bool =
     True` and `result_table: str | None = None`. The per-file loop passes
     `raise_if_empty=False` and its own iteration-scoped `result_table`, so
     one zero-overlap file (under default drop behavior) doesn't abort a
     batch that still produces output from other files; the equivalent
     check instead runs once, post-loop, against the fully folded result.
   - `step` MUST be `None` whenever multiple `input_paths` are given
     (`ValueError` otherwise), mirroring ADR-0023's identical rule: the
     per-file loop has no clean external resumption point matching the
     five named stages. This is a user-visible behavior change from
     before this ADR (previously unrestricted).
   - `--debug` exports only the final accumulated tables; no per-file
     debug export exists, the same as `edge-clip`'s multi-file mode.
   - The `merge_columns` child-schema collision check
     (`core.assign._carry_forward_columns`, see ADR-0077 and
     [[feedback_error_on_collision]]) stays lazy, per file: a collision
     only present in a later file's schema is only caught on that file's
     iteration, after earlier files already did real work. This wastes
     work but never corrupts output, since nothing is written to the
     final destination until the whole loop succeeds. A pre-scan of every
     file's schema up front would close this gap but adds real complexity
     for a failure mode that's rare and non-corrupting.
3. **`--merge` replaces `--carry-column`/`--on-unmatched`.** `carry_columns:
   list[str] | None` and `on_unmatched: str` are removed from
   `mosaic()`'s signature entirely, replaced by one parameter,
   `merge_columns: list[str] | bool = False`: `False` (default) turns both
   attribute-carrying and gap-fill passthrough off; `True` (bare `--merge`)
   carries every parent column (resolved once via `DESCRIBE
   {name}_parent_01`, excluding `fid`/`geom`) and turns passthrough on;
   a list (`--merge iso_3,adm0_name`, comma-splittable like the old
   `--carry-column`) narrows the carried columns to just those, passthrough
   still on. `passthrough = bool(merge_columns)` is correct for all three
   states. `merge_columns is True` is resolved to an explicit column list
   once, early, before it's ever passed to `core.assign`'s existing
   `carry_columns` parameter, which stays list-only and unaware of the
   boolean/all-columns concept, keeping it a neutral leaf.

## Consequences

`edge-mosaic`'s multi-file batches now hold roughly (parent + one children
file) in memory at any point instead of (parent + every children file),
matching the memory-constrained deployment targets in CLAUDE.md, at the
cost of losing per-step resumability for multi-file runs (new: `step` now
raises `ValueError` there) and of one extra "renumber `fid`" pass at the
end to keep the previously-documented "fid is renumbered fresh after the
union" contract (`docs/explanation/edge_mosaic.md`) true under the new
per-file assembly. `--carry-column`/`--on-unmatched` no longer exist for
`edge-mosaic`; any caller using either must switch to `--merge`, a breaking
CLI/API rename, not an addition. `edge-mosaic`'s CLI surface is otherwise
unchanged (glob expansion, repeated `--input`); this ADR is an internal
reimplementation of the multi-file path plus a flag rename, not a new
user-facing capability beyond what ADR-0078 already shipped.

References, does not supersede, ADR-0023 and ADR-0024 (the pattern being
reused) and ADR-0077/ADR-0078 (the two features `--merge` now couples).
