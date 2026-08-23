# 0066: `map` no longer requires embedding to enter the chain, or assumes admin0 exists

## Status

Accepted. Supersedes ADR-0064's embedding-gated code eligibility and
ADR-0057's position-based admin0 exclusion (those ADRs stay as the
historical record of the earlier approach; neither is edited).

## Context

Testing against DRC's real `cod_adm1.shp`/`cod_adm2.shp` surfaced a bias
ADR-0064 baked in: it assumed a country-level p-code is always the root
every other code embeds. `cod_adm1.shp`'s `adm0_pcode` is ISO3 (`"COD"`)
while `adm1_pcode` is built from ISO2 (`"CD10"`); no embedding relationship
exists, so the whole file resolved nothing. `cod_adm2.shp` has no country
column at all, so its real, non-constant admin1 (`adm1_pcode`, count 26)
was excluded outright by ADR-0057's "chain position 0 is always excluded"
rule, treating a genuine level as if it were a constant admin0 placeholder.

Both failures trace to the same root cause: a coarser grouping that
genuinely nests (containment holds) but isn't embedding-related to its
child is common, not an edge case. Admin1 is the first true sub-national
unit and may be numbered completely independently of any country code, or
have no country column present at all. A file may also mix codes and
names freely between levels, so gating chain *entry* on
code-shaped-and-embedding conflates two separate questions: whether a
column nests at all, and whether it plays the `code` or `name` role once
it does.

A real compound code (DRC's `adm2_pcode` `"CD5204"` containing `adm1_pcode`
`"CD52"`) has both containment and embedding. A genuinely-nesting but
independently-numbered level (DRC's ISO3 admin0 vs ISO2-prefixed admin1;
Madagascar's old `PROV_CODE_` vs `ADM1_PCODE`) can have containment
without embedding. Requiring embedding for every edge conflates these two
cases; requiring it for none reopens the exact problem ADR-0065's
`supplemental` tier was built to solve, letting a coarser grouping
(`PROV_CODE_`) hijack a real level's chain slot. The fix distinguishes
them structurally instead of by embedding universally: a *constant*
column (`COUNT(DISTINCT) = 1`) has no variation to test embedding against
in the first place, so it's exempt; anything with real variation still
needs an embedding-justified edge, or a companion-count tie-break, to earn
its slot.

## Decision

1. `_build_level_groups()` groups **every** non-excluded/non-noise
   column, code or name alike, by `COUNT(DISTINCT)` and verified pairwise
   bijection (clustered, not gated by a whole-bucket unanimity check: two
   columns merge if bijective with each other, regardless of a third
   column sharing their count but not their bijection).
2. `_build_chain()`'s DAG edge validity becomes: containment holds, and
   either the coarser group's count is exactly 1 (a true constant, exempt
   from the embedding check), or some column in the finer group embeds
   some column in the coarser group.
3. When multiple candidates tie for the longest path, `_build_chain()`
   prefers the one with more verified same-level companion columns (a
   code+name pair beats a lone column), then the one with the higher
   (finer) count.
4. Admin-level exclusion becomes value-based, not position-based: a
   resolved level is excluded from output only when its own count is
   exactly 1. A non-constant level is never excluded regardless of its
   rank in the chain, even at position 0.
5. Code/name role assignment becomes a per-level, post-chain decision: a
   column that embeds its level's resolved parent is `code`; a sibling
   that doesn't is `name` when at least one sibling did embed. When
   nothing in the group embeds the parent (independently-numbered codes,
   a lone column, or a level with no parent at all), fall back to
   `_looks_code_shaped()`: a majority of non-null values containing a
   digit is `code`, otherwise `name`.

## Consequences

`cod_adm1.shp` now resolves `adm1_pcode`/`adm1_name` correctly; its
constant `adm0_pcode`/`adm0_name` stay excluded via the count-1 rule, not
a hardcoded position. `cod_adm2.shp` now resolves both of its real levels
instead of dropping the coarser one; since the file has no country
column, the coarsest resolved level is still labeled by relative rank
(`adm0_*`) rather than its real admin number, a pre-existing, documented
limitation (`docs/explanation/map.md`'s "not modeled in v1"), now
surfaced to a human for manual renaming instead of silently dropped.
Madagascar's `PROV_CODE_`/`OLD_PROVIN` still resolve to `supplemental`,
since the companion-count tie-break favors `ADM1_PCODE`+`ADM1_EN`'s
two-column companion group over the lone `PROV_CODE_` column at the same
path length.

The "ambiguous, level unknown" note (a code-eligible column that never
joined any chain position) becomes mechanically unreachable: with no
embedding pre-filter gating chain entry, a column either joins the chain,
lands in a bracket (`ambiguous`/`supplemental`/`name`), or is genuinely
`unmatched` by cardinality alone. `docs/reference/map.md` and
`docs/explanation/map.md` drop that note form.
