# 0091: opportunistic level-0 fallback in schema-fill

## Status

Accepted

## Context

`fieldmaps/admin-boundaries` has territories with ADM0 geometry but zero
sub-national source rows. It wants `adm1_id`..`adm4_id` to fall back to
`adm0_id` and `adm_lvl` to read `0` for those rows, using the same
COALESCE-family machinery `schema-fill` already has for every other level.
`detect_levels()` (`core/schema_fill/_levels.py`) excluded level 0 from its
returned range unconditionally, so a row with no non-NULL code at any level
1..N ended up with every hierarchy column and `adm_lvl` NULL, even when an
always-present `adm0`-shaped code column existed on the table.

Making level 0 part of the unconditional default range was rejected: the
range `detect_levels()` returns is *required*, not just detected, so a
table with adm1-4 columns but no `adm0`-prefixed column (the common case,
since admin0 is usually the separate parent/clip file rather than a column
on the child) would go from succeeding to raising `ValueError`. A
`min_level`/`include_level_zero` opt-in flag was also considered and
rejected: it would add API/CLI surface with no use beyond toggling exactly
this one case, when the presence of the level's own code column is already
the same signal `detect_levels()` uses to require every other level.

## Decision

`detect_levels()` prepends `0` to its returned level list iff
`schema.code_field.format(n=0)` is present among the table's columns,
never requiring it. `_column_families()` and `_02_fill.main()`
(`core/schema_fill/_02_fill.py`) needed no change: both already operate
generically over whatever `levels: list[int]` is passed in, and
`_depth_column_sql()` already iterates levels deepest-first, so a level-0
code column naturally becomes the final fallback `WHEN` case. No new
kwarg or CLI flag was added.

## Consequences

A table with no level-0 code column behaves exactly as before: level 0
never enters the detected range. A table that does have one (e.g.
`adm0_id`) now gets it folded into the same fill/depth-stamp pass as every
other level automatically, with `adm_lvl` reading `0` for a row whose
deepest non-NULL code is at level 0. The one residual risk is a table that
happens to carry an `adm0`-shaped code column not intended as a hierarchy
level; this is judged acceptably narrow since it requires an exact match
on `schema.code_field`'s own template, the identical name-pattern
assumption every other level in this tool already relies on.
