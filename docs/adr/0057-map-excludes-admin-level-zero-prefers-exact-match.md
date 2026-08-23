# 0057: `map` excludes admin level 0 and prefers an exact bijective match

## Status

Accepted. Refines ADR-0056: its grouping/numbering mechanism stands
unchanged; its constant-level exception is replaced by an unconditional
admin-level-0 exclusion.

## Context

Re-running ADR-0056's design against the real Madagascar file surfaced
two more problems.

1. At admin level 1, `ADM1_EN` (a real region name, count 24, exactly
   matching `ADM1_PCODE`'s own count) got grouped and renamed alongside
   `PROV_CODE_`/`OLD_PROVIN` (Madagascar's old 6-province system, count
   6). The old province columns land in the same cardinality bracket
   `(1, 24]` and pass the one-directional function check (many admin1
   codes legitimately share one old-province value), but they're not
   admin1 companions, they're a different, coarser, undiscovered level
   that happens to overlap the bracket range. `ADM1_EN` is distinguished
   by a strictly stronger signal the old province columns lack: it's
   fully bijective with `ADM1_PCODE` (every name value maps back to
   exactly one code too), not just a function of it.
2. At admin level 0, `ADM0_EN` ("Madagascar") and six unrelated constant
   columns (`ADM1_TYPE`..`ADM4_TYPE`, `PROV_TYPE`, `NOTES`, values like
   "Region"/"District"/"Fokontany") are structurally identical: same
   shape (a single word), same count (1), same trivial function check.
   Telling "Madagascar" apart from "Region" requires reading what the
   words mean, the vocabulary signal this tool has ruled out from the
   start (ADR-0054). User direction: stop trying to resolve admin level
   0 at all; `map` suggests admin level 1 and finer only.

## Decision

1. A name-shaped candidate that's also bijective with its level's code
   (every code value maps to exactly one candidate value **and** every
   candidate value maps to exactly one code value) is an exact match and
   wins over a merely functional one; when at least one exact match
   exists at a level, only exact matches are grouped/numbered, and every
   other bracketed candidate stays `ambiguous` with a note naming the
   exact match. When no candidate is exactly bijective (e.g. a real name
   column with legitimate cross-parent repeats, count lower than its
   code's), matching falls back to ADR-0056's looser function check.
2. Admin level 0 is never resolved: `main()`'s code-chain loop and
   `_bracket_other_columns()` both skip any chain position whose
   resolved level is `0`, whether or not `--own-level` is given (without
   `--own-level`, the chain's coarsest rank is always relative level 0).
   No `missing` gap row is synthesized for level 0 either. Level-0
   columns fall through to the ordinary `unmatched` tier, kept under
   their own name.

## Consequences

`ADM1_EN` now resolves alone at admin level 1; `PROV_CODE_`/`OLD_PROVIN`
stay `ambiguous`, referencing it. Admin level 0 (`ADM0_PCODE`, `ADM0_EN`,
and the constant-tie columns from ADR-0056) is never suggested by `map`
at all, for any file; a user fills in admin0's crosswalk row by hand,
which is a small, constant, one-row-per-file edit. A file whose data
never reaches real admin level 1 or finer (an admin-0-only file) gets no
suggestions from `map` at all; this is accepted, consistent with the
decision to not attempt admin0 resolution under any circumstance.
