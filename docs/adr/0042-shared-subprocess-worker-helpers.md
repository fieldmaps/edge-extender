# 0042: shared subprocess-worker helpers in `core.duckdb_utils`

## Status

Accepted.

## Context

`core/match/_02_groups.py` (per-group `extend` subprocess) and `core/clip/
_engine.py` (per-`parent_fid` clip subprocess) each independently spawn an
isolated `multiprocessing` worker and wait on it: `multiprocessing.
get_context("spawn")`, `ctx.Queue()`/`ctx.Process(...).start()/.join()`,
then the identical `result_queue.get() if not result_queue.empty() else
"worker exited with no result..."` fallback idiom. Each worker entry point
also independently wraps its body in the same try/except-put-error-on-queue
shape, needed because a spawned process's exception would otherwise vanish
silently instead of surfacing in the parent.

This duplication predates `clip` being extracted as its own leaf
(`docs/adr/0015` through `0017`): `match` had the pattern first, `clip`
copied its shape when it split out. Unlike other legacy-bias cases in this
codebase, extracting it isn't match-only cleanup slated to evaporate when
`match` is eventually dropped: `clip` is permanent, so a shared helper
improves code that outlives `match` too.

## Decision

Two new functions in `topo_tools/core/duckdb_utils.py` (already the leaf
both files import `get_connection`/`log_file` from):

- `spawn_worker(target, args) -> tuple[int | None, str | None]`: creates
  the spawn context/queue/process, starts and joins it, and returns
  `(exitcode, error_or_None)`. Uses `clip`'s more detailed "no result"
  fallback wording (it additionally notes a non-OOM spawn-startup failure
  as a possible cause) as the one shared message; no test asserted on the
  old, less detailed wording `match` used.
- `worker_result(result_queue)`: a context manager wrapping a worker
  body's try/except, putting `None` on success or `f"{type(e).__name__}:
  {e}"` on any exception.

Each caller keeps its own post-spawn decision: `clip` still raises
immediately on the first failed `parent_fid` (aborting the whole run);
`match` still logs and records the failure into its issues table,
continuing to the next group. That divergence (`docs/adr/0020`) lives in
the caller, not the shared helper.

## Consequences

`core/match/_02_groups.py` and `core/clip/_engine.py` each drop ~15-20
lines of duplicated boilerplate. No behavior change beyond the unified
"no result" fallback message text. `docs/explanation/match.md`/`clip.md`
narrate the subprocess/queue mechanism at the level of *why* (isolation,
error signaling), not *where the code lives*, so neither needed editing.
