# 0020: Match moves to two subprocess generations (extend, then batched clip)

## Status

Accepted.

## Context

Before the assign/clip/stitch extraction, `match`'s per-group subprocess ran
`extend`'s pipeline and then clipped to that group's parent in the same
subprocess, via `core/clip.py`'s `assign_table=None` mode (already isolated
by the caller, so clip skipped its own per-`parent_fid` isolation). That
special case is removed as part of the extraction: `core/clip/` now always
isolates per distinct `parent_fid` in its own spawned subprocess, uniformly
for every caller including `match`.

`match` therefore moves to two subprocess generations per run: a per-group
`extend`-only subprocess (unchanged in count/shape), followed by a second,
later generation of per-`parent_fid` clip subprocesses (mosaic's existing
mechanism), batched over the whole reassembled table. This changes both the
peak-memory shape (all groups' extended-but-unclipped output now sits in
`{name}_03a` before clip runs, instead of each group being clipped
immediately) and adds ~1,120 extra subprocess spawns at Colombia scale, so
it needed empirical re-verification, not just a mechanical refactor.

## Decision

Adopt the two-generation design as-is, with clip's existing hard-fail-on-
first-bad-`parent_fid` semantics applying uniformly to `match` too — a
single bad `parent_fid` now aborts the whole run, rather than match's old
per-group continue-past-failure behavior for clip failures specifically
(per-group `extend` failures still continue, dropping just that group, as
before).

## Consequences

Re-verified against the exact Colombia-scale case from
`docs/explanation/match.md` (portolan `col/latest/adm3` →
`col/latest/adm2`, `--debug`; 31,880 children / 1,122 parents, 1,120 with at
least one assigned child), output written outside the read-only portolan
catalog:

| Stage    | Baseline (fused, pre-extraction) | This run (two generations) |
| -------- | --------------------------------- | --------------------------- |
| inputs   | 1m06s                              | 59s                          |
| assign   | 57s                                | 10s                          |
| groups   | 30m45s                             | 29m24s                       |
| clip     | (fused into groups)                | 5m13s                        |
| stitch   | 53s                                | 46s                          |
| outputs  | 2m02s                              | 1m51s                        |
| **total**| **35m44s**                         | **38m23s**                   |
| peak RSS | 5.26 GB                            | 7.23 GB                      |

All 1,120 groups and all 1,120 clip subprocesses succeeded: zero dropped
children, zero failed groups, zero issues rows, output row count (31,880)
exactly matches input child count. No OOM at any point — the two-generation
subprocess design still reliably reclaims GEOS's native heap between units
of work, which is the property the whole isolation architecture exists to
preserve.

Wall time grew ~7% (the extra ~1,120 clip subprocess spawns), in line with
expectations and not a concern at this scale. Peak RSS grew ~37% (5.26 GB →
7.23 GB), confirming the plan's flagged risk: holding all groups' extended-
but-unclipped output in `{name}_03a` before clip runs does measurably raise
peak memory versus the old immediately-clipped-per-group design. This peak
occurs during clip's own batched pass and the final `stitch` coverage-clean,
not during `groups` itself, so it doesn't change per-group memory pressure —
only the single-run peak for very large countries. Accepted as a real but
bounded cost of the extraction; worth revisiting only if a future
larger-than-Colombia real-world case is found to OOM under it.
