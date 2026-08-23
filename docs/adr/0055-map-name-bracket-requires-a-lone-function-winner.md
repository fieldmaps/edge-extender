# 0055: `map`'s name bracketing requires a lone function-passing winner

## Status

Accepted. Refines ADR-0054's cardinality-bracketing step; does not
supersede it.

## Context

Running ADR-0054's design against the real Madagascar admin4 shapefile
(17,465 rows) surfaced two problems cardinality bracketing alone doesn't
handle:

1. `ADM0_PCODE`'s only value is `"MG"`, letters only, no digit suffix, so
   it fails `_CODE_SHAPE_REGEX` and gets classified name-shaped instead
   of code-shaped. COD-AB's admin0 pcode is genuinely just the bare
   ISO2/3 country code by convention, an exception the regex validated
   in ADR-0054 never accounted for.
2. Once a level's cardinality bracket is established, *every* column
   whose distinct count falls in it gets crowned that level's name,
   with no check that more than one candidate landed there. On the real
   file, level 1's bracket (`1 < count <= 24`) caught not just the real
   `ADM1_EN` but also `PROV_CODE_`, `OLD_PROVIN` (a legacy province
   attribute that happens to also partition along current admin1
   boundaries), `SOURCE`, and `Multipart` (a vertex-count-style
   attribute). All 5 silently collided on the single target column
   `adm1_name`, which isn't just a matching-quality problem, an unedited
   crosswalk with duplicate `target_column` values fails
   `refactor`'s duplicate-target check outright.

A same-level function check (does every value of this level's code map
to exactly one value of the candidate, `GROUP BY code HAVING
COUNT(DISTINCT candidate) > 1`) was tested empirically and rejects
`SOURCE`/`Multipart` (9 and 13 violating groups). It does not resolve
every case: constant columns (distinct count 1) trivially pass this
check for every other constant column, since there's only one group,
so `ADM0_EN`, `ADM1_TYPE`..`ADM4_TYPE`, `PROV_TYPE`, and `NOTES` all
pass it identically at level 0. This is a genuine identifiability limit:
without any name/vocabulary signal, a constant per-file text attribute
is structurally indistinguishable from a real constant admin-level name.

## Decision

Two changes to ADR-0054's algorithm:

1. A constant (distinct count 1) column whose sole value matches
   `^[A-Z]{1,4}$` (bare uppercase letters, no digits) is reclassified
   code-shaped, recovering bare-ISO-code admin0 pcodes.
2. Bracketing a name-shaped column into a level now additionally
   requires it pass the same-level function check against that level's
   code column. Among the columns bracketed to one level, the column is
   only promoted to confidence `name` if it's the **sole** column that
   both is name-shaped and passes the function check; if two or more
   tie, or every candidate fails the check, they're all left `ambiguous`
   with a note naming the tied companions (or explaining the failure),
   each keeping its own original column name as `target_column`. Nothing
   is auto-resolved, nothing collides, the same posture ADR-0052
   established for genuine ambiguity.

## Consequences

On the real Madagascar file, levels 2-4 (finer, higher-cardinality
levels where only the real name column has that level's exact
cardinality and is a function of its code) resolve cleanly and
unambiguously: `ADM2_EN`/`ADM3_EN`/`ADM4_EN` each correctly win their
level with no competing candidate. Levels 0-1 (coarser levels where
several legacy/incidental attributes share the bracket) surface as
multi-way `ambiguous` ties instead of a silent, broken collision, an
honest reflection of the fact that pure value-shape/cardinality signals
cannot always uniquely identify "the" name column, not a regression: the
old vocabulary-matching design also couldn't identify `PROV_CODE_`/
`OLD_PROVIN` as anything meaningful, it just never surfaced them as
candidates for anything.

A file where a genuine name column happens to share exact cardinality
with an unrelated function-passing column (e.g. two attributes that both
vary 1:1 with a level's code, purely coincidentally) will still tie and
require human disambiguation, even when only one of them is "correct."
This is accepted, consistent with `map` never auto-applying anything
itself.
