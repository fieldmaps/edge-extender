# 0071: `map` tolerates one missing-value sentinel value in a code column

## Status

Accepted.

## Context

Syria's raw `Sub__District.shp`/`Admin_Unit.shp` genuinely nest ADM1 -> ADM2
-> ADM3 via compound p-codes (`SY02` -> `SY0200` -> `SY020000`), but rows
missing a finer code carry the literal string `"No_Pcode"` instead of NULL.
That one recurring value appears under many different real parents, so it
alone breaks both `_containment_holds` (`GROUP BY finer HAVING COUNT(DISTINCT
coarser) > 1` picks it up as its own violating group) and `_embeds`
(`contains(child, parent)` fails for every row carrying it), even though
every other row's real code embeds and nests cleanly. `map` doesn't know
this literal string means "missing", and hardcoding it (or any other
per-agency placeholder spelling) would be exactly the kind of fragile,
vocabulary-based matching the project avoids.

`_embeds`/`_containment_holds` already tolerate NULL as "no evidence
either way". A single recurring placeholder string behaves identically in
every way that matters structurally: it's one specific value, reused across
many rows that should otherwise be evidence, contributing nothing when
excluded rather than actively contradicting the relationship the way a
second, independently-real conflicting value would.

## Decision

`_containment_holds()` tolerates the violation if excluding it leaves at
most one violating `GROUP BY finer` group; more than one distinct violating
value falls back to strict (a real, unexplained anomaly, not a single
placeholder). `_embeds()` tolerates a failure the same way: if every row
that fails `contains(child, parent)` shares one single `child` value, that
value is excluded before deciding pass/fail. Neither function ever inspects
what the value actually is (no `"No_Pcode"`-specific check anywhere); the
sole criterion is that exactly one distinct value explains every violation.

This is deliberately narrower than a percentage-based noise tolerance: a
file with several genuinely different anomalous values (e.g. Syria's
`Admin_Unit.shp`, where `SY14` duplicates five different district codes
across multiple real governorates, not one placeholder) still fails
strictly, since more than one distinct violator remains unexplained.

## Consequences

Syria's `Sub__District.shp` now resolves its full ADM1/ADM2/ADM3 chain via
real embedding instead of falling back to `docs/adr/0070`'s no-embedding
fallback or collapsing unrelated levels together. `Admin_Unit.shp`'s ADM1
level stays `ambiguous` relative to ADM2, since its own violation (`SY14`,
five distinct offending values) is a genuine multi-value anomaly the
tolerance correctly declines to paper over. Re-validated against every
real file tested this session: no regression on any file whose containment/
embedding checks already passed cleanly (single-violator tolerance only
changes a prior failure into a pass, never the reverse).

A count-bucketed pair that differs by exactly one due to the same kind of
single-row anomaly (e.g. a point layer where one facility's name doesn't
match its own pcode) isn't covered here: `_build_level_groups` buckets
columns by raw `COUNT(DISTINCT)` before any bijection check runs, so two
otherwise-companion columns whose raw counts differ by even one never reach
`_containment_holds` together at all. Not addressed by this decision.
