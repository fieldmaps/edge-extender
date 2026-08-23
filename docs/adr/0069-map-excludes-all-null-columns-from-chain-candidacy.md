# 0069: `map` excludes all-null columns from chain group formation

## Status

Accepted.

## Context

Angola's `Comuna_2025.shp` has two entirely-null fields, `Cod_D_Urb` and
`Nome_D_Urb` (`COUNT(DISTINCT) = 0` each, confirmed against the raw
file). `_containment_holds()` treats an all-null column as trivially
containing, and being contained by, anything (`COUNT(DISTINCT NULL)` is
always 0, never `> 1`), so two all-null columns test as bijective with
each other with no real data backing it. Before ADR-0068's noise-column
fix, this file's `OBJECTID_1` (a GDAL collision-suffixed duplicate,
`COUNT(DISTINCT) = 1`) was still in the candidate pool and won the chain
root by ADR-0066's constant exemption, so the null pair never got a
chance to compete. Once `OBJECTID_1` was correctly excluded as noise, no
other true constant remained in the file, nothing else in it embeds
anything, so every real column was stuck at the same one-node path
length, and the tie-break (more same-level companions wins) picked the
all-null pair over the file's real, populated `Nome_Comun` (541 distinct
communes), since two null columns still count as two trivially "bijective"
companions.

This is the same gap `_embeds()` already closes for embedding evidence
("no row exists where both sides are non-null, so there's no evidence
either way"), just missing from chain group formation.

## Decision

`main()` (`core/map/_02_map.py`) filters candidate columns to
`counts[c] > 0` before calling `_build_level_groups()`/`_build_chain()`.
An all-null column never enters chain-group formation, so it can never
win a chain slot, constant-exempt or otherwise. It remains in the full
column list for bracketing and the final fallback loop, so it still
appears in the crosswalk, correctly resolving to `unmatched` (its
`COUNT(DISTINCT)` of 0 can never satisfy any bracket range either, since
every bracket lower bound is `>= 0`).

## Consequences

`Nome_Comun` resolves to the file's coarsest real level again once the
all-null pair can no longer contest it, now labeled level 0 (rather than
level 1, since the file's own real, non-constant coarsest level is now
correctly the first resolved position) instead of level 1, consistent
with `map` never assuming an admin0 that isn't there (ADR-0066).
`Cod_D_Urb`/`Nome_D_Urb` still surface in the crosswalk as `unmatched`,
`note` empty, same as any other column with no resolvable evidence.
