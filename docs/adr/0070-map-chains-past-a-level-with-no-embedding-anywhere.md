# 0070: `map` chains past a level lacking embedding, if the file has no embedding anywhere

## Status

Accepted.

## Context

DRC's GRID3 health-facility layers (`GRID3_COD_health_areas_v8_0.gdb`) nest
`province` -> `antenne` -> `zonesante`/`zs_uid` -> `airesante`/`as_uid`, a
genuine four-level hierarchy, but none of the finer levels' values embed
their parent's value as a substring: `antenne` is a plain facility-zone name
("Gbadolite"), not a compound code built from the province name or code.
Per `docs/adr/0066`, a non-constant chain edge requires embedding
justification, so the chain stopped at `province`, leaving `antenne`,
`zonesante`, `zs_uid`, `airesante`, `as_uid` all `unmatched`, even though
containment (`_containment_holds`, already checked across every coarser/
finer column pair, not just one) held cleanly at every step.

Embedding exists specifically to rule out coincidental containment: two
unrelated attributes can satisfy a functional containment relationship by
chance, especially in a small file, so `map` requires a second, independent
signal (a compound code literally built from its parent's value) before
trusting a non-constant edge. That signal simply doesn't exist in a file
whose deepest levels only carry names, not compound codes; requiring it
there makes `map` refuse to resolve a real, verifiable hierarchy.

## Decision

`_build_chain()` (`core/map/_02_map.py`) computes, once per file, whether
any coarser/finer group pair anywhere in the candidate DAG has embedding
evidence at all. If none do, every non-constant edge in that file falls
back to containment alone (already the strictest form: every coarser
column paired with every finer column must satisfy containment, not just
one lucky pair) instead of requiring embedding. A file that has embedding
evidence anywhere keeps the stricter per-edge rule from `docs/adr/0066`
unchanged, so a file mixing code-based and name-based levels doesn't get
a spurious skip-edge from unrelated attributes coincidentally agreeing.

This why-no-embedding-anywhere signal cannot by itself distinguish "this
file has no compound-code convention" from "this file has one, but every
edge's embedding evidence happens to be destroyed by the same data-quality
issue" (see `docs/adr/0071`, which removes that second case from the
picture by tolerating a single missing-value sentinel).

## Consequences

GRID3's health-facility layers resolve the full `province` -> `antenne` ->
`zonesante` -> `airesante` chain instead of stopping at `province`. A file
that already has any embedding evidence anywhere is unaffected: confirmed
byte-identical output across 85 of 87 real files re-tested after this
change, the other 2 affected only by the `docs/adr/0071` interaction.
