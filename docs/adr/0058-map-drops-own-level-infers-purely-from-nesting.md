# 0058: `map` drops `--own-level`, infers levels purely from nesting depth

## Status

Accepted. Supersedes the `own_level` mechanism introduced alongside
ADR-0052 and relied on by ADR-0056/ADR-0057's numbering and gap-row
design; those ADRs' grouping/exact-match/admin0-exclusion decisions stand
unchanged.

## Context

`own_level` let a caller anchor the discovered code chain's finest column
to a real admin number, with two consequences: `target_column` only used
the schema's numbered template when `own_level` was given (silently
falling back to the source column's own name otherwise), and a
`missing` gap row was synthesized per level in `1..own_level` with no
resolved code/name. Running `map` without the flag (the default) on a
real Madagascar shapefile therefore produced a crosswalk that didn't
rename anything, which the user had not been told to expect and did not
want. User direction, given directly: `map` must always use the
templated target column name, and must never require a flag to do so; it
should determine each column's admin level by inferring nesting depth
alone.

## Decision

1. `own_level` is removed entirely: the parameter/kwarg from
   `core.map._02_map.main()`, `api.map.map()`, `api.crosswalk.crosswalk()`,
   and the `--own-level`/`OWN_LEVEL` CLI option from both `map` and
   `crosswalk`.
2. A chain position's level number is always its relative rank in the
   discovered code chain (0 = coarsest); this was already the behavior
   when `own_level` was omitted, now it's the only behavior.
3. `target_column` for every resolved `code`/`name` row is always
   rendered from the schema's template at that level; there is no
   fallback to the source column's own name for a resolved row.
4. Gap-row (`missing`) synthesis is removed along with it: without a
   caller-supplied expected level count, `map` has no basis for asserting
   a level is missing rather than simply absent from this file. The
   `CONFIDENCE_MISSING` tier is deleted.
5. The "too small for the discovered chain" `ValueError` is removed; it
   only existed to validate `own_level` against the chain length.

## Consequences

`map` run with no flags now always produces the same output the old
`--own-level`-anchored path did for a file's own real hierarchy depth,
since ADR-0057 already made the coarsest chain position "admin level 0,
never resolved" unconditional. The one behavior change: a source file
whose coarsest discovered code column is *not* actually admin level 0
(e.g. a state-level file with no country-level column at all) still gets
that coarsest position excluded, mislabeled as admin0, since `map` has no
signal left to tell the two cases apart without a vocabulary or human
input, the same accepted-limitation philosophy as ADR-0057's admin0
exclusion itself. A user with such a file edits that one row by hand,
same as an admin0 row today.
