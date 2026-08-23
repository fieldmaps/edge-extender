# 0056: `map` groups and numbers multiple candidates at the same level

## Status

Accepted. Supersedes ADR-0055's tie-breaking decision (its constant-code
reclassification and same-level function check both stand unchanged).

## Context

Running ADR-0055's design against the real Madagascar admin4 shapefile
resolved levels 2-4 cleanly but left levels 0-1 as multi-way `ambiguous`
ties (e.g. `ADM1_EN` and several legacy attributes all passing the
function check at level 1). User feedback on that result: ties are not a
failure to route around, they're legitimate multiple names/codes at one
level (a dataset may carry `state_name` alongside a second language or
legacy name column), and `map`'s job is to organize the hierarchy, not to
arbitrate which single candidate is "the" name. The desired output groups
every structurally-legitimate candidate at a level under that level's
target template, numbered, rather than picking one winner or refusing to
resolve any of them.

A first implementation applied this uniformly to every level, then
regressed against the real file: level 0 (constant, single-country) is
where a name column's function check is trivially true for *any* other
constant column, so unrelated attributes (`ADM1_TYPE`..`ADM4_TYPE`,
`PROV_TYPE`, `NOTES`) all "passed" and got renamed `adm0_name1`..
`adm0_name6` alongside the real `ADM0_EN`, actively mapping columns the
user explicitly didn't want touched.

## Decision

Every candidate that passes ADR-0055's per-role check (bijective same-
count companion for codes, function-check-passing name-shaped for names)
is renamed and kept, not just a sole winner. Candidates at one level are
numbered by their source-column order: the first gets the bare template
(`adm2_name`, `adm2_pcode`), each subsequent one gets the template plus
an appended integer starting at 1 (`adm2_name1`, `adm2_pcode1`, ...). A
column that fails its role's check (shape-ambiguous, or not a function of
that level's code) still falls back to `ambiguous`, keeping its own
column name, same as before.

Exception: a **constant** level (its code column has a single distinct
value) can only resolve a sole winner, never a group, since its function
check can't discriminate between candidates there. Two or more name
candidates at a constant level all stay `ambiguous` instead of getting
numbered.

## Consequences

On the real Madagascar file, level 1's legitimate name candidates
(`ADM1_EN` plus other function-passing name-shaped columns) now resolve
and rename instead of surfacing as an unresolved tie; incidental
non-function attributes (`SOURCE`, `Multipart`) are unaffected, still
`ambiguous`. The same numbering applies to bijective code companions at
one level, closing a latent duplicate-target gap in ADR-0055's code path
that no real file had exercised yet. Level 0 keeps ADR-0055's original
lone-winner-or-ambiguous behavior: `ADM0_EN` resolves alone, and the six
other file-wide-constant attributes stay `ambiguous` rather than being
renamed as if they were admin0 names.
