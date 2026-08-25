# 0024: Cache the parent's tile decomposition across clip's per-file loop

## Status

Superseded by ADR-0080 (this caching mechanism moved to `edge-mosaic`,
see ADR-0079; standalone `edge-clip` reverted to a strict 1:1 primitive).

## Context

ADR-0023 fixed multi-file `clip`'s memory blowup by processing one children
file at a time behind a shared parent load. Running the real 111-country
portolan batch against that design turned up a large wall-clock regression.
An earlier end-to-end benchmark against this same fieldmaps world adm0
parent (315 features, all 111 countries' children merged into one file, one
`assign` pass, one `clip` pass) measured `assign-one` at ~2.5 minutes and
`clip` at ~9.5 minutes total. ADR-0023's per-file loop was on track to take
multiple hours for the same 111 countries.

The cause: `core/assign/_02_one.py`'s `_build_pairs()` grid-tiles every
high-vertex parent part (`subdivide_boundary`, reused from `core.clip`)
before joining children to it. That tiling is pure geometry work on the
parent alone, it never reads the children table, but the ADR-0023 per-file
loop calls `assign_stage.main()` (and therefore `_build_pairs()`) once per
children file, so the same tiling of the same unchanging parent gets redone
from scratch on every one of the 111 iterations. Confirmed by reading
`_build_pairs()`: the parent-part/vertex-count table and the per-heavy-part
`subdivide_boundary` calls depend only on `{name}_parent_01`, never on
`{name}_child_01`.

## Decision

`core/assign/_02_one.py` gains a new public function, `prepare_parent_tiles()`,
containing exactly the parent-only work `_build_pairs()` did before this
change, now writing to persistent table names (`{name}_02_parent_parts`,
`{name}_02_parent_tiles`) instead of call-scoped temp ones. `_build_pairs()`
and `main()` both gain a `use_cached_tiles` keyword (default `False`):
`False` reproduces the original single-call behavior exactly (calls
`prepare_parent_tiles()` itself, drops the cache tables when done); `True`
skips straight to the children-dependent join, assuming a caller already
populated the cache tables.

`api/clip.py`'s `_clip_each_file()` calls `prepare_parent_tiles()` once,
right after loading the parent and before the per-file loop starts, then
passes `use_cached_tiles=True` on every iteration's `assign_stage.main()`
call. The cache tables live for the whole run, dropped alongside
`{name}_parent_full` at the end (unless `--debug`).

As a side effect, the heavy-part join itself is now one set-based
`JOIN ... GROUP BY child_fid, parent_fid` against a single combined tiles
table (each tile already tagged with its own `parent_fid`), replacing a
Python loop that issued one query per heavy part. This benefits every
caller, not just the cached path: `mosaic` and single-file `clip` still
call `prepare_parent_tiles()` once per run exactly as before, just with a
cheaper join afterward.

`mosaic`'s and single-file `clip`'s existing call sites
(`assign.main(conn, name)` / `assign_stage.main(conn, name)`) are
unaffected, since `use_cached_tiles` defaults to `False`.

## Consequences

Multi-file `clip` runs now tile the parent's heavy parts once per run
instead of once per file, bringing wall-clock much closer to the ~9.5
minute combined-run baseline while keeping ADR-0023's per-file memory
footprint (only one file's children resident at a time). The cache tables
(`{name}_02_parent_parts`, `{name}_02_parent_tiles`) are one more thing
`--debug` leaves on disk for the whole run rather than per file, alongside
`{name}_parent_full`.
