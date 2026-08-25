# 0077: `core.assign` carries forward caller-named parent columns

## Status

Accepted.

## Context

Fitting a global admin4 layer assembled from many per-country already-
extended files (e.g. `mdg/latest/adm4/extended.parquet`) into one global
adm0 polygon layer via `edge-mosaic` leaves every matched child with no
adm0 attributes (iso codes, region groupings) beyond the numeric
`parent_fid` that `core.assign` already produces. ADR-0050 already frames
attribute enrichment as out of scope for a pure geometry/topology tool, so
any fix must not become a general-purpose attribute-join tool; it has to
ride on a spatial match `core.assign` already computes for `edge-clip`,
`edge-mosaic`, and `edge-match` alike.

The child and parent layers in the motivating case use different column
conventions for the same concept (`iso3` vs `iso_3`), which rules out
inferring a join column from name or value shape. `schema-map`'s own
design already rejects that approach for its own crosswalk inference
(structure only, never column names/values); this feature follows the
same principle: column names to carry are always caller-specified.

## Decision

1. `assign_one` (`core/assign/_one.py`) and `assign_many`
   (`core/assign/_many.py`) both gain an optional
   `carry_columns: list[str] | None = None` kwarg, since both are shared by
   every caller (`edge-clip`, `edge-mosaic`, `edge-match`) and neither
   should special-case the other.
2. Implementation is append-only: `_02_assign` is built exactly as before,
   then, only if `carry_columns` is truthy, one more `CREATE OR REPLACE
   TABLE` joins the finished table back to `{name}_parent_01` on
   `parent_fid`, projecting the named columns. `_02_assign`'s schema is
   byte-identical to today's when `carry_columns` is omitted.
3. A name colliding with `_02_assign`'s own reserved columns (`child_fid`,
   `parent_fid`, `assignment_method`, `spatial_agrees`) raises `ValueError`
   before any SQL runs. A collision with the child's own schema is left to
   fail loudly at the SQL layer (DuckDB rejects a duplicate column name);
   no separate check is added for that case.
4. `core/edge_clip/_01_clip.py` and `core/edge_mosaic/_01_clip.py` thread
   `carry_columns` into their existing `SELECT c.*, a.parent_fid` joins.
   `core/edge_match/_02_groups.py` joins `_02_assign` for the first time
   (it previously bolted `parent_fid` on after each group's subprocess
   returned); carried columns cross the subprocess boundary as ordinary
   Parquet columns, surviving `edge-extend`'s merge stage the same way any
   other child attribute column already does.
5. Every layer above `core.assign` (`api.edge_clip.clip()`,
   `api.edge_mosaic.mosaic()`, `api.edge_match.match()`, and each tool's
   CLI command via a repeatable, comma-splittable `--carry-column`) passes
   `carry_columns` straight through with no interpretation.

## Consequences

A caller can enrich matched children with any parent attribute by name,
with no assumption about what columns exist on either layer. Unmatched
children never gain these columns (see ADR-0078 for `edge-mosaic`'s
opt-in passthrough, which fills them as NULL via `UNION ALL BY NAME`
rather than through any join). A future reference-based backfill for
gap-filled countries (joining against a separate lookup table by ISO
code, say) is a distinct, deliberately unbuilt capability; NULL is the
whole of today's behavior for anything `core.assign` never matched.
