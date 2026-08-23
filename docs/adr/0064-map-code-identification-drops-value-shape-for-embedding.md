# 0064: `map` identifies codes by parent-value embedding, chains by DAG longest path

## Status

Accepted. Supersedes ADR-0054's value-shape regex for code identification
and its single-pass adjacent-groups chain walk (that ADR stays as the
historical record of the earlier approach; it is not edited).

## Context

Running `map` against every raw national source file in
`hdx-cod-ab-ai/data` (not the hand-curated Madagascar fixture ADR-0054
was validated against) showed the p-code shape regex
(`^[A-Za-z]{1,4}[0-9]+$`) producing a completely empty crosswalk on most
genuinely-raw files: Angola's pure-numeric province code, Burundi's
compound codes with a prefix longer than 4 letters, Paraguay's
pure-numeric department/district codes, and GRID3-derived DRC health-zone
GUIDs (`3f9a1c...`-style) all fail to match a shape assumed from COD-AB's
own convention. Real source data cannot be trusted to follow any
particular shape convention at all; a looser regex just moves the
false-negative/false-positive boundary around without fixing the
underlying premise.

The fix is a purely relational, constructive test instead: a real
hierarchical code is *built* by concatenating a parent's code onto a
local suffix (Madagascar's `ADM4_PCODE` contains `ADM3_PCODE` contains
`ADM2_PCODE`...), so it textually contains its parent's value. Checking
containment directly, via `contains(child, parent)`, requires no shape
assumption at all, and correctly identifies a GRID3 GUID as *not* a code:
GUIDs are independently random per row, so nothing embeds anything.

Validating this against Paraguay's actual admin data surfaced two further
real patterns:

- `pry_admin2.parquet`'s `DISTRITO` is a per-department LOCAL numbering
  (resets `01`..`31` within each `DPTO`), globally low-cardinality (31)
  despite there being many more real districts; `CLAVE` is the true
  compound code (`DPTO+DISTRITO`). A cardinality-only rule (ADR-0054's
  original chain-building) can't tell a local reused number from a real
  code; embedding can, since `CLAVE` embeds `DPTO` and `DISTRITO` doesn't.
- `pry_admin3.parquet` has a deeper compound chain
  (`DPTO` -> `CLAVE`(dept+district) -> `CLV_AREA`(+area) ->
  `CLAVE_BAR`(+barrio)) where `AREA` (only 3 distinct values, an
  urban/rural/mixed classifier) is baked into the compound codes'
  construction without being a real nested administrative unit itself. A
  single-pass adjacent-groups chain walk (ADR-0054's `_chain_from_groups`)
  would need `AREA` itself to nest cleanly as an intermediate step; it
  doesn't, and severing there would cut `CLAVE_BAR` off from the rest of
  the chain even though `CLAVE_BAR` does still nest under `DPTO`/`CLAVE`.

Two further generalizations were needed once embedding replaced shape as
the eligibility test: a file with no country column at all still needs
its true coarsest level to self-anchor with nothing coarser to embed
against (generalizing ADR-0054's "keep constant columns" special case to
"the file's own minimum-cardinality column(s) qualify unconditionally");
and an all-null legacy/schema column (a `valid_to`/`lang1`-style column
kept null for one particular file) must not vacuously "pass" the
embedding check against everything else just because no row exists where
both sides are non-null to find a counterexample.

## Decision

1. `_is_code_like()` replaces the shape regex: a column is code-eligible
   if its own `COUNT(DISTINCT)` equals the lowest *positive*
   `COUNT(DISTINCT)` among all candidate columns (an all-null column's 0
   never counts as this minimum), or if every one of its non-null values
   contains the corresponding non-null value of some other candidate
   column with a strictly lower `COUNT(DISTINCT)`. The embedding check
   (`_embeds()`) requires at least one row where both sides are non-null;
   zero such rows means no evidence, not a pass.
2. `_build_chain()` replaces the single-pass adjacent-groups walk with a
   longest-path dynamic-programming search over the full containment DAG:
   every coarser/finer pair of level-groups is tested for containment,
   not just cardinality-neighbors, and the longest path end to end is the
   discovered hierarchy. This lets a finer compound code reconnect to its
   real ancestor past a level that doesn't nest cleanly on its own.
3. The corroborating "prefix-starts-with" signal ADR-0054 surfaced in a
   chain row's `note` is dropped: embedding is now the primary
   eligibility test itself, so a separate weaker corroboration on top of
   it is redundant.

## Consequences

Every previously-empty file tested this session now resolves a real
hierarchy: Angola (`Cod_Alfa_N` = `"AOZRE02"` embeds country `"AO"`),
Burundi, and Paraguay's `pry_admin2`/`pry_admin3` (correctly distinguishing
`CLAVE`'s real compound code from `DISTRITO`'s local reused number, and
correctly routing `CLAVE_BAR` past the non-nesting `AREA` classifier).
GRID3-style opaque GUIDs correctly stay unresolved: no embedding evidence
exists to justify placing them in the chain at all, which is more honest
than a coincidental-cardinality guess.

A code column with no embedding evidence anywhere in the file (an opaque
GUID, or a genuinely independent per-level numbering convention that
never concatenates its parent's value) is now unrecoverable by this
design; ADR-0054's cardinality/containment-only chain-building could
sometimes resolve such a case by coincidence (matching cardinality
alone), which this change intentionally gives up in exchange for not
producing a confident, code-shaped guess out of pure column-position
coincidence (see the GRID3-style `structural_hierarchy_input` fixture in
`tests/test_crosswalk.py`, changed this session to embed its two levels'
codes for exactly this reason).

The "file's own minimum cardinality auto-qualifies" rule could, in
principle, mis-anchor level 0 on an unrelated low-cardinality categorical
column if a file has no true constant admin0 column and some unrelated
attribute happens to have fewer distinct values than the file's real
coarsest level. No real dataset examined during this session exhibited
this; not engineered around further absent a concrete case.
