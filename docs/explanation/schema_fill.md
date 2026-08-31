# schema-fill

`schema-fill` stamps a new depth column, `adm_lvl` by default (overridable
via `depth_column`/`--depth-column`), recording each row's real, pre-fill
depth, then pins every admin-hierarchy column past that depth to the row's
own value at (or nearest below) that depth (e.g. a row whose real depth is
admin1 gets `adm2_code`/`adm2_name`/`adm3_code`/`adm3_name` filled in from
that same admin1 unit, while a row whose real depth is admin2 with a
genuinely NULL `adm2_name` keeps that NULL at `adm3_name` too, rather than
reaching further up to admin1's name). It reuses `schema-map`'s
`TargetSchema` mechanism (`docs/explanation/schema_map.md`) to discover the
hierarchy generically, from any dataset's own naming convention, never a
hardcoded P-code-shaped assumption; `name_field` and `code_field` are
matched independently, so they need not share a literal prefix.

## Why this exists

`fieldmaps/admin-boundaries`'s `app/_03_build/_03b_clip.py` builds a global
admin1-4 layer from a leaf-level source where many rows are only attributed
down to admin1 or admin2 (a territory with no real admin3/4 subdivision, or
source data that simply doesn't go that deep). Its hand-rolled
`_leaf_attr_select()` fills every level down from whatever's present using
`COALESCE`, purely to make a single flat leaf table dissolvable at every
level afterward; it carries no signal distinguishing a genuine admin3 row
from an admin1 row whose admin3 columns were only ever filled down; a
caller inspecting the leaf table alone cannot tell the two cases apart.

`schema-fill` closes that gap directly: once a leaf table is properly
attributed (every row's real depth stamped), `dissolve` needs no
special-casing at all to build every level 1..N. `dissolve`'s existing,
unmodified auto-keep-constant-column behavior (any column constant within
a group is kept via `any_value`) is what makes the depth column survive
automatically through a chain of per-level `dissolve` calls, with zero new
code in `dissolve` itself: dissolving to admin2 keeps `adm_lvl` at
whatever depth was genuine for each resulting group (e.g. `3` if any
admin3 unit existed under it, `2` if it never went deeper). An earlier
design considered a single composite `dissolve-hierarchy` tool that
filled and dissolved every level in one call; it was dropped once it
became clear `schema-fill` (fill) followed by plain `dissolve`, called
once per level, needs no bespoke tool at all (see `docs/adr/0075`).

## Pipeline order: run after mosaic/stitch, not before

`schema-fill` is meant to run against an already-clipped, already-stitched
layer (`edge-match`'s or `edge-mosaic`'s output), not a raw pre-clip
source: the target schema is already settled by that point (every parent's
own attribute columns are present on every child row after clip), so
`schema-fill`'s level detection has real code/name columns to key off of.
Running it earlier, against raw per-level source files before they've been
matched into a single coherent hierarchy, has nothing to detect a level
from yet.

## Pipeline

1. **`_01_inputs`**: reads and reprojects to EPSG:4326 via the shared
   `core.io.read_and_reproject()` helper (`{name}_01`), then immediately
   calls `detect_levels()` to raise early if any level 1..N is missing its
   own code column.
2. **`_02_fill`** (`core/schema_fill/_02_fill.py`): builds the `depth_column`
   CASE expression (`_depth_column_sql()`) keyed off the *original*,
   pre-fill code columns inside a `WITH "depth" AS (...)` CTE, then groups
   every level column by shared suffix (`column_families()`,
   `core/schema_map/_levels.py`), run once against `code_field`'s own
   prefix and once against `name_field`'s own prefix (skipping the second
   pass when they're the same prefix). For each family, a level `L`'s
   column stays untouched (`CASE WHEN "{depth_column}" >= L THEN own_col
   ELSE (fallback) END`) whenever `L` is at or before a row's own real
   depth; past that, it takes `fallback`: the family's own deepest column at
   or below the row's real depth (`CASE WHEN "{depth_column}" >= lvl THEN
   col ... END`, tested descending), whatever that column's raw value is,
   NULL included, never searching further up the family's own chain. A
   single-level family is left as pure passthrough (`{name}_02`). The
   prefix scan picks up every same-prefix suffix it finds, not just
   `code_field`/`name_field` themselves: fieldmaps' `adm{n}_id`,
   `adm{n}_src`, `adm{n}_name`, `adm{n}_name1`, `adm{n}_name2` (one
   alt-language name column per language) land in five independent
   families and all get filled, with no extra configuration.
3. **`_03_outputs`**: exports `{name}_02` directly. No hard gate: like
   `schema-map`, this tool only touches attribute columns, never geometry.

## Level detection

`detect_levels()` (`core/schema_map/_levels.py`, shared with `dissolve`'s
`target_schema` option, see `docs/explanation/dissolve.md`) reuses the schema's own
`code_field` prefix (the literal text before its `{n}` placeholder, e.g.
`"adm"`) to find every present level via a regex match against the
table's columns, then requires every level in `1..max_level` to have its
own code column, raising `ValueError` naming exactly which level(s) are
missing otherwise. This is what lets the pattern auto-extend to a single
detected level (e.g. an admin1-only input) with no special-casing: `levels`
is simply `[1]`, and the fill/depth-stamp logic runs unchanged.

Level 0 is opportunistic rather than required: `detect_levels()` prepends
it to the returned range whenever the table already has its own level-0
code column (e.g. `adm0_id`), and simply leaves it out otherwise, so a
table with no level-0 column behaves exactly as before. This closes the
gap for datasets like `fieldmaps/admin-boundaries`, where a territory has
ADM0 geometry but zero sub-national source rows: `adm1_id`..`adm4_id` fall
back to `adm0_id` and `adm_lvl` reads `0`, through the same per-family
fill machinery used for every other level (see `docs/adr/0091`).

## Why the fill pins to each row's own real depth, not a COALESCE search

An earlier design filled a level `L`'s NULL value with a `COALESCE` search
back up the ancestor chain (`L`, `L-1`, ..., `1`), regardless of whether
`L` was itself a row's real terminal level. That silently invented data at
a row's own genuinely-NULL terminal value: a province with no recorded
local-language name at its own real depth would still get one, copied down
from its country's name one level up, once a caller filled a level past
it. A short-lived interim fix pinned that search to one caller-supplied
reference level (`cascade_from_level`) instead of every shallower level,
but that pin was a single value applied to the whole input file; it could
only be used correctly on a file where every row shared the same real
depth, and silently overwrote genuine deeper data on any file mixing
countries at different depths.

Since `schema-fill` already computes each row's own real depth
(`depth_column`) as a byproduct, that computed depth is used directly as
the pin, automatically, per row, with no caller-supplied level and no
file-wide assumption: a row whose real depth is 2 is filled relative to 2,
a row whose real depth is 3 in the very same input file is filled relative
to 3, and a genuinely NULL value at either row's own real depth is left
NULL rather than backfilled from a shallower ancestor (see `docs/adr/0093`).
