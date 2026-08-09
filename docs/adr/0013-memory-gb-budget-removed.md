# 0013: `--memory-gb` starting-distance budget tried, then removed

## Status

Accepted

## Context

`attempt.py` needs a starting `DISTANCE` for Voronoi resampling. An
intermediate design derived it from a `--memory-gb`-parameterized point
budget, fitted from probes run inside a real memory-constrained container.
It worked for the immediate problem (Chile, previously OOMing even at the
old hardcoded default, succeeded), but `_01_inputs.py`, `_02_lines.py`, and
`_05_merge.py`'s whole-table `ST_CoverageClean` pass have no `DISTANCE`
lever at all and routinely exceed a 4GB ceiling regardless
(`phl_admin3` needs ~5.9GB, `idn_admin3` ~5.4GB, a real Colombia `match()`
run peaked at 5.26GB during merge). A container genuinely bounded to 4GB
was never achievable pipeline-wide, so budget-tuning one stage was mostly
theater; real headroom has to come from swap or a larger container either
way, and `--memory-gb` was never wired into DuckDB's own `memory_limit`.

(Verifying this under a real container also surfaced a Docker Desktop
gotcha: the VM's own total-memory cap can silently sit below the
`--memory` flag passed to `docker run`, under-testing every container run
until the VM is restarted to pick up its own settings. Always check
`docker info`'s `Total Memory` against the `--memory` flag actually being
passed before trusting a container test.)

## Decision

Removed `--memory-gb` entirely. `attempt.py` instead computes
`effective_distance = MIN(DEFAULT_DISTANCE, natural_res)`, where
`natural_res` is the median real segment length; this lets files with
finer native detail than `DEFAULT_DISTANCE` (e.g. Philippines) start
sharper, with no memory-budget parameter at all. The existing
doubling-retry loop still handles any failure, including the one
non-SIGKILL case the budget also protected against (raw vertex count alone
exceeding a sane starting distance).

## Consequences

`phl_admin3`'s `_01_inputs.py` `ST_CoverageClean` pass (~5.9GB) and
`idn_admin3`'s `_02_lines.py` neighbor-union self-join (~5.4GB) are known,
`DISTANCE`-independent memory floors with no runtime gate; a future OOM on
either file is an expected, already-diagnosed cost, not a regression to
chase. Don't reintroduce a `--memory-gb`-style runtime memory-budget check:
a check that can only log a line isn't worth the upkeep of the
probe-fitted constants it needs, and real headroom must come from swap or a
larger container instead.
