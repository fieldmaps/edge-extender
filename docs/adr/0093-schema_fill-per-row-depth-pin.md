# 0093: `schema-fill` pins the cascade to each row's own real depth

## Status

Accepted.

## Context

ADR-0075's default fill searched a `COALESCE` chain back up the ancestor
chain (`L`, `L-1`, ..., `1`) for every level `L`, regardless of whether `L`
was itself a row's real terminal level. That silently invented data at a
row's own genuinely-NULL terminal value: a province with no recorded
local-language name at its own real depth still got one, copied down from
its country's name one level up, once a caller filled a level past it
(issue #20, the Algeria/DZA case).

An interim fix, shipped in the same PR as this ADR but never released,
added `cascade_from_level`/`--cascade-from-level`: a caller-supplied
reference level past which every family value is duplicated verbatim from
that one level, no further `COALESCE` search. That fixed the invented-data
problem, but only for a file where every row shared the same real depth;
the pin was one value applied file-wide, and it silently overwrote genuine
deeper data for any row in the file that happened to go deeper than the
pinned level.

`schema-fill` already computes each row's own real depth as `depth_column`,
a byproduct of the fill it was already doing. That computed depth can drive
the same pin automatically, per row, with no caller-supplied level and no
file-wide assumption.

A `target_level`/`--target-level` padding capability (synthesizing
brand-new columns past a file's own detected max level, for a caller that
needs a fixed schema depth regardless of what a file structurally reaches)
was considered alongside this change and dropped: every real call in this
project runs `edge-match`/`edge-mosaic` once across every country in the
world in a single invocation, so `UNION ALL BY NAME` already guarantees the
deepest columns present anywhere in that one call reach every row (NULL
until the per-row pin fills them), since some country always goes to
admin4. There is no invocation boundary left for a padding flag to
compensate for.

## Decision

`depth_column` becomes the unconditional pin for every fill, replacing both
the original `COALESCE`-to-level-1 default and `cascade_from_level`, which
is removed. `core/schema_fill/_02_fill.py` computes `depth_column` once,
in a `WITH "depth" AS (...)` CTE, then for each column family (grouped by
shared suffix, as before) and each level `L` present in that family:

- If a row's own `depth_column` is `>= L`, `L`'s value is left completely
  untouched, NULL included: `L` is at or before the row's own real depth,
  so whatever it holds is real data, not a fill artifact.
- Otherwise, `L` takes the family's own fallback value: the deepest column
  the family has at or below the row's own real depth (`CASE WHEN
  "{depth_column}" >= lvl THEN col ... END`, tested descending), whatever
  that column's raw value is. This does not search further up the family's
  chain past that one fallback column, matching `cascade_from_level`'s
  verbatim-duplication behavior, just computed per row instead of once
  file-wide.

The descending `>=` test (not exact `=`) is required because a family need
not have a column at every level (e.g. an alt-language name column present
at levels 1-2 but not 3): exact-match would null out a legitimately
present value whenever a row's real depth doesn't land exactly on a level
the family has, reintroducing a version of the same invented/discarded-data
bug this change exists to fix.

`schema-fill` also gains a guard: it raises `ValueError` if `depth_column`
already names an existing column on the input, rather than producing a
silent DuckDB column-collision error deep in the generated SQL.

## Consequences

`cascade_from_level`/`--cascade-from-level` is removed from
`core.schema_fill`, `api.schema_fill.fill()`, and the CLI; the fill is now
fully automatic with no flag to reason about. The one test whose expected
*value* changes: `test_mismatched_name_code_prefixes_both_fill`'s second
row had a genuinely-NULL name at its own real depth, previously backfilled
from a shallower ancestor (the exact bug class this ADR fixes), now stays
NULL. A column family with an internal gap (present at levels 1 and 3 but
not 2, for a row whose real depth is 2) still resolves to level 1's value
via the fallback's descending scan; this is untested and left as a known
limitation, since no real target schema in this project has ever had a
non-contiguous family.
