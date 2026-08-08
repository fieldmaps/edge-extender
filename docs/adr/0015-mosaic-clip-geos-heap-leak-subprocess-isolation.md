# 0015: mosaic's clip step needs per-parent subprocess isolation, not just batching

## Status

Accepted

## Context

Continent-scale testing (46 African countries, ~24k children, adm4-deepest-
available per country) OOM'd `mosaic`'s clip step at the same ~12.7GB ceiling
(this machine's default DuckDB `memory_limit`, ~80% of 16GB RAM) regardless
of thread count (10 vs. 2) or batching one `INSERT` per distinct assigned
parent fid instead of a single join across all parents. Adding a `CHECKPOINT`
after every per-parent `INSERT` made no measurable difference either.

Root-caused via direct measurement, not assumption: `duckdb_memory()`'s own
per-tag total never exceeded ~453MB at any point across 40 of 46 parents
processed, while process RSS (via `ps aux`) fluctuated 1.4-3.7GB, already far
exceeding DuckDB's own tracked total, and the run still crashed with the
identical `12.7 GiB/12.7 GiB used` error. Ruled out: thread-count/parallelism
(identical failure at default threads and threads=2); raw data volume (only
~382MB combined WKB children+parent, nowhere near the ceiling); DuckDB's own
buffer-pool/WAL accounting (`CHECKPOINT` had zero effect); per-parent batching
alone (delayed the crash from immediate to ~40/46 parents in, didn't prevent
it).

This is the same class of problem already documented for `match`: GEOS's
native heap isn't fully released even after closing a DuckDB connection
(`docs/explanation/match.md`), which is why `match` isolates each group's
`extend()` call in a subprocess. The new finding here is that this leak
doesn't require `extend()`'s Voronoi machinery at all — repeated plain
`ST_Intersection` calls within one long-lived process leak the same way,
contradicting `mosaic`'s founding assumption ("no subprocess isolation
needed since we skip `extend()`'s heavy Voronoi work").

## Decision

`clip_to_parent`'s `assign_table` branch (`topo_tools/core/clip.py`) runs
each distinct parent fid's clip in its own spawned OS subprocess
(`multiprocessing.get_context("spawn")`), mirroring `match`'s existing
per-group pattern: child/parent rows written to Parquet, a fresh subprocess
reads them, intersects, writes `output.parquet`, and the parent process
appends the result and lets the subprocess exit before moving to the next
parent fid. Requires a `tmp_dir` argument (raises `ValueError` if omitted
with `assign_table` set) — `match`'s own call site (`assign_table=None`)
needs no isolation since it already runs inside `match`'s own per-group
subprocess.

## Consequences

`clip_to_parent`'s public signature grew `tmp_dir`/`threads`/`debug` keyword
arguments; `core/mosaic/_03_clip.py::main` and `api/mosaic.py`'s clip step
call site both pass them through. Regression-verified against the West
Africa cluster (8 countries, 653 output rows / 0 issues, unchanged across
this fix). This fix alone was insufficient at continent scale: one single
parent (South Africa, 4,392 admin4 children against a 281k-vertex parent
boundary) still OOM'd fully isolated in its own subprocess, since the leak
across parents and the cost of one single oversized intersection are
different problems. See ADR-0016 for that fix.
