# 0065: `map` splits a losing bracket candidate into `supplemental` or `ambiguous`

## Status

Accepted. Refines ADR-0057's "every other function-passing candidate stays
`ambiguous`, naming the exact match" rule (that ADR stays as the historical
record of the earlier wording; it is not edited).

## Context

Reviewing Madagascar's real admin4 crosswalk by hand surfaced `PROV_CODE_`
and `OLD_PROVIN`, the pre-2009 six-province system: both land in admin1's
cardinality bracket, pass the same-level function check against
`ADM1_PCODE`, but lose the exact-match tiebreak to `ADM1_EN`/`ADM1_PCODE`
(the current 24-region system). ADR-0057's wording called this
`ambiguous`, `note` naming the exact match. The user objected: the old
provinces are a real, well-defined administrative concept, not an
ambiguous one, and losing a tiebreak to a bijective companion doesn't make
a column any less well-defined. The user wants exactly this kind of
coarser regional grouping surfaced as a candidate supplemental column to
keep by hand, not filed under the same label as a genuinely uncertain
column.

A losing, non-bijective, function-passing candidate turns out to always be
this kind of case, never a same-level near-tie: by pigeonhole, an onto
function between two sets of equal cardinality is automatically
one-to-one too, so a candidate that passes the one-way function check
(`GROUP BY code HAVING COUNT(DISTINCT candidate) > 1` returns zero rows)
but fails the reverse direction cannot share the level's cardinality; it
must be strictly coarser. There is no case reachable through this branch
where a "loser" is actually a same-level rival, so naming the exact match
in its `note` (`"see ADM1_PCODE"`) added no information a human couldn't
already infer from the level number alone, and was dropped.

The genuinely uncertain case is different: a column that fails the
one-way function check entirely (neither a subset nor superset of the
level, cross-cutting) has no defensible relationship to report beyond
"this landed near level `k` by cardinality alone." Madagascar's own
`SOURCE` column is exactly this: it fails the function check against
`ADM1_PCODE` in both directions (confirmed by direct query), so it stays
`ambiguous`. Burundi's `TYPE` column is a third case: it's code-eligible
(embeds nothing, but ties the file's minimum-count anchor under a
coincidence) yet never joins any position in the discovered chain, the
real manifestation of the false-anchor risk ADR-0064 flagged as
un-engineered-around; it has no level to report at all, so its note
became `"ambiguous, level unknown"` rather than the vaguer prior
"doesn't fit chain" wording.

## Decision

1. Add `CONFIDENCE_SUPPLEMENTAL = "supplemental"` alongside
   `CONFIDENCE_AMBIGUOUS = "ambiguous"` (`core/map/_constants.py`).
2. In `_bracket_other_columns()`, when an exact match exists at a level,
   every other function-passing (one-way containment) candidate becomes
   `supplemental` instead of `ambiguous`; a candidate that fails the
   function check entirely stays `ambiguous`.
3. Standardize every unresolved note to one of three fixed forms, with no
   free-form clause and no `"see X"` pointer:
   - `"ambiguous, level unknown"`: a code-eligible column that never
     joined any chain position.
   - `"ambiguous, level {k}"`: a bracketed column that fails the
     function check in both directions.
   - `"supplemental, superset of level {k}"`: a bracketed column that
     passes the function check but loses the exact-match tiebreak.

## Consequences

Madagascar's `PROV_CODE_`/`OLD_PROVIN` now read `"supplemental, superset
of level 1"`, `SOURCE` reads `"ambiguous, level 1"`, and Burundi's `TYPE`
reads `"ambiguous, level unknown"`, each independently reviewable without
cross-referencing another column's name. `refactor` is unaffected, since
both tiers still leave `target_column` empty.

The three-form standardization removes the ability to attach any
free-form context to a note beyond tier and level; if a future case needs
more explanation than a level number provides, it will need a fourth tier
or a schema change, not a `note` addition.
