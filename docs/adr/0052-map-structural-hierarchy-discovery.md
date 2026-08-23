# 0052: `map` detects admin hierarchy structurally, not by vocabulary

## Status

Accepted.

## Context

`map` (then named `schema-propose`) was tested against a real FileGDB
(GRID3 DRC health zones, 519 rows). Its columns (`province`/`prov_uid` at
health-province level, `zonesante`/`zs_uid` at health-zone level) form a
genuine two-level admin hierarchy, but none of that vocabulary (French,
GRID3-specific) matches the bundled `cod-ab.yaml` schema's aliases or
patterns, so every one of those columns came back `unmatched`. Pure GIS
bookkeeping columns (`OBJECTID`, `Shape_Length`, `Shape_Area`) cluttered
the output as `unmatched` too. Output order was also just the source
file's own column order, not useful for comparing against the target
schema.

Extending the alias vocabulary was rejected as a real fix: an arbitrary
source file will never natively use the target schema's vocabulary,
that's the entire reason a crosswalk tool exists. A structural fix, one
that detects hierarchy from the data itself, independent of column
naming, was required instead.

## Decision

Add a fourth matching pass, structural hierarchy discovery, running only
on columns still unclaimed after the existing exact/nesting/pattern
passes, with zero vocabulary or target-schema involvement:

1. Compute `COUNT(DISTINCT col)` for every remaining candidate column in
   one query, then drop constant columns (a constant column trivially
   "contains" everything and would falsely anchor as a coarsest level).
2. Group remaining columns by identical distinct-count. A group of more
   than one column is accepted as same-level companions only if verified
   truly bijective in both directions; a same-count group that fails this
   check is demoted to singleton columns rather than discarded, so each
   one still gets a chance to chain with a different-cardinality
   neighbor.
3. Sort groups by shared count ascending and walk adjacent pairs, joining
   only if every cross-pair containment check holds. A failed join splits
   the run there into independent chains rather than invalidating the
   whole pool, since the pool bundles many otherwise-unrelated columns
   together.
4. Every column in a validated chain of two or more groups gets a new
   confidence tier, `hierarchy-detected`, `target_column` set to its own
   original name (never guessing a name-vs-pcode role), and a note naming
   the chain, rank, same-level companions, and relation to the next
   level. It is explicitly not associated with any target-schema field.
   A chain of length one falls through to `unmatched` instead.

`core.constants.NOISE_COLUMNS` (a shared leaf constant, not `map`-only) is
excluded from candidate columns entirely, addressing the bookkeeping-
column clutter separately from hierarchy detection.

Output ordering changed to three sections: target-schema-anchored rows
(in schema declaration order, including a new synthesized gap row per
target field with zero mapped source columns, confidence `missing`),
then structural hierarchy chains (by chain, then rank), then pure
`unmatched` columns last in source order.

`refactor` (the apply-side tool) required matching compatibility changes:
it must skip blank-`source_column` rows (gap-row placeholders) instead of
raising, and exclude `NOISE_COLUMNS` from its source-column coverage
check, so an unedited `map` crosswalk still applies cleanly.

## Consequences

A structurally-coincidental pair of columns that happens to share
cardinality and containment by chance, without being a real hierarchy,
can still surface as a false-positive `hierarchy-detected` chain. This is
mitigated by human review via the note text (a human sees the claimed
relationship before handing the crosswalk to `refactor`), not by a
suppressing heuristic, consistent with `map` never auto-applying anything
itself.

Structural detection can only establish relative order and grouping, not
identity: it never assigns a chain to a target-schema field, a concrete
admin-level number, or a name-versus-pcode role within a same-level
group. All three are left for a human to decide when hand-editing the
crosswalk, the same "nothing silently disappears, nothing auto-resolved"
posture the existing nesting-inference pass already takes.
