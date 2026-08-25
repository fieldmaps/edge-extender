# 0076: `map` tolerates a near-bijective bracket winner as a numbered sibling

## Status

Accepted. Refines ADR-0065's "a function-passing, non-bijective bracket
candidate at an already-named level is always `supplemental`" rule; ADR-0065
stays as the historical record of that rule's original scope (Madagascar's
genuinely coarser `PROV_CODE_`/`OLD_PROVIN` case), not edited.

## Context

Real fieldmaps `admin-boundaries` output (`adm{n}_id`/`adm{n}_src`/
`adm{n}_name`/`adm{n}_name1`/`adm{n}_name2`) and the independent portolan
`wld/adm4.parquet` corpus (`adm{n}_pcode`/`adm{n}_name`/`adm{n}_name1`/
`adm{n}_name2`/`adm{n}_name3`) both carry legitimate alt-language name
columns at the same level as a primary name, e.g. Turkey's TUR-20220101
adm2 (`adm2_name1`, Turkish script) and Thailand's THA-20220122 adm2
(`adm2_name1`, Thai script). Turkey's alt name is exactly bijective with
the primary and already clusters via `_cluster_by_bijection`, unaffected.
Thailand's is not exactly bijective, 5 real cases (e.g. two districts both
romanized to the English "Bang Sai" but genuinely distinct in Thai script),
so ADR-0065's rule sends it to `supplemental` today, forcing a hand-edit of
the crosswalk for what is, empirically, a 99.5%-accurate translation column
(923/928 distinct, 0.5% collapse).

ADR-0065's own pigeonhole proof still holds (a function-passing,
non-bijective candidate must be strictly coarser than the level), so some
real collapse is unavoidable for any candidate reaching this branch; the
question is how much collapse is still consistent with "same level,
imperfect transcription/translation" versus "a genuinely coarser grouping".
Two independently produced real corpora (fieldmaps'
`edge-matched/intl/adm4_polygons.parquet`, portolan's `wld/adm4.parquet`)
were swept across every country/level/candidate pair with this shape.
Genuine alt-name candidates topped out at 21.4% collapse (Thailand adm3
`name1`, confirmed independently by both corpora) and 24% (Mongolia adm2
`name1`, fieldmaps only); genuinely coarser candidates (Morocco adm2/3/4
`name1`, Haiti adm2 `name2`, Algeria adm2/3/4 `name1`, Sri Lanka adm4
`name2`) started at 85.5% and ranged to 97.6%. No candidate in either
corpus fell between 24% and 85%.

An earlier design compared a candidate's own collapse to the *primary*
name column's own collapse at the same level, on the theory that a
candidate should only need to be "as clean as" its sibling. This was
dropped: Cameroon's primary `adm2_name`/`adm3_name` is itself badly
collapsed in both corpora (an upstream data defect, ~10 distinct values
for 58-360 units) while its `adm2_name1`/`adm3_name1` is perfectly unique;
a primary-relative comparison would have permitted an essentially-
arbitrary candidate collapse ratio there, or wrongly rejected a perfectly
good 0%-collapse candidate for being "too much better" than a broken
primary. Comparing a candidate only to the level's own unit count avoids
depending on an unrelated column's own data quality entirely.

## Decision

1. `_bracket_level()` (`core/schema_map/_02_map.py`) computes each winning
   candidate's own collapse ratio, `1 - COUNT(DISTINCT candidate) /
   level_unit_count`, from data already in hand (`counts[column]`,
   `chain[level][0]`), no new query.
2. When the level already has a resolved chain `name` member, a winning
   candidate becomes a numbered sibling (`name1`, `name2`, ...), same as
   any other same-level/same-role grouping (ADR-0056), when its own
   collapse ratio is `<= 0.30`; otherwise it stays `supplemental`
   (ADR-0065's original rule, unchanged above the threshold).
3. `0.30` is chosen with margin on both sides of the observed
   genuine-translation ceiling (~24%, two corpora) and the observed
   coarser-grouping floor (~85.5%, both corpora); it is a starting default,
   not a value tuned to a single case, and is explicitly flagged for
   re-validation against the fuller portolan catalog before being treated
   as final (see `docs/how-to/at-scale-testing.md`).
4. When the level has no resolved chain `name` member yet, the first
   winning candidate's classification is unaffected: it still becomes the
   level's `name` unconditionally, with no collapse-ratio gate, exactly as
   before. This decision only changes the fate of an *additional*
   candidate at an already-named level; the exact-bijection chain-
   clustering path (`_cluster_by_bijection`/`_build_level_groups`), used
   for the primary code/name role assignment itself, is untouched.
5. The same check applies uniformly regardless of whether a winning
   candidate is code-shaped or name-shaped: `_bracket_level()` has never
   distinguished shape for its winners, an existing, unrelated limitation
   not addressed here (see Consequences). No code-side near-miss evidence
   was found in either real corpus; the 0.30 default is applied to both
   roles for consistency rather than a code-specific number, since there
   is no evidence yet to justify a different one.

## Consequences

Thailand's `adm2_name1` (0.5% collapse) and Mongolia's `adm2_name1` (18%)
now resolve as `level1_name1` instead of `supplemental`. Algeria's
`adm2_name1` (96.9%), Morocco's, Haiti's, and Sri Lanka's equivalents stay
`supplemental`, unaffected, since they fall far outside the threshold band.
Turkey's `adm2_name1` is unaffected either way, it already resolves via
exact bijection. Cameroon's `adm2_name1`/`adm3_name1` now resolve correctly
regardless of how collapsed the primary `adm2_name`/`adm3_name` happens to
be, since the new check never references it.

`_bracket_level()`'s winning candidates still all get `role="name"` and
`schema.name_field` templating regardless of shape, an existing gap this
ADR does not close (a genuinely coarser alternate code column that wins a
bracket, e.g. because no chain name exists yet, is still mis-templated
with the name field); if a real file surfaces this, it needs its own
investigation and ADR, not a silent fix bundled here.

`0.30` was derived from two real corpora but not yet the full portolan
catalog; a future ADR may adjust it once broader coverage is run (see
`docs/how-to/at-scale-testing.md`), the same "narrow, then broaden"
pattern already used for ADR-0064/0070/0071.
