# 0025: clip's per-parent-fid subprocess always clears its group_dir first

## Status

Accepted.

## Context

`core/clip/_engine.py`'s `main()` names each parent fid's subprocess
working directory `{tmp_dir}/{table_out}_p{parent_fid}`, where `table_out`
is `{name}_03`. In `api.clip._clip_each_file()` (ADR-0023's multi-file
loop), `name` is constant across every children file in the run, so two
different children files that happen to get assigned the same
`parent_fid` (plausible against a shared world admin0 parent, and observed
running the full portolan batch) produce the same `group_dir`. Under
`--debug`, `main()` skips its `shutil.rmtree(group_dir, ...)` cleanup so
the directory can be inspected afterward; that same skip means the second
file's subprocess opens a working directory still holding the first file's
leftover DuckDB catalog, and its `CREATE TABLE clip_one` collides:

```
CatalogException: Catalog Error: Table with name "clip_one" already exists!
```

This was latent in ADR-0023's design from the start (unrelated to
ADR-0024's tiling cache), just not triggered until a real multi-file
`--debug` run reused a `parent_fid` across files.

## Decision

`_engine.main()` now clears `group_dir` (`shutil.rmtree(..., ignore_errors=True)`)
immediately before `mkdir`, unconditionally, regardless of `debug`. The
existing end-of-iteration cleanup (skipped under `--debug`, so the
directory survives for post-run inspection) is unchanged; only the
start-of-iteration state is now always guaranteed empty.

## Consequences

A `--debug` run of clip's multi-file loop still only shows the *last*
usage of any given `parent_fid`'s group_dir on disk afterward (consistent
with ADR-0023's existing debug caveat that multi-file `--debug` isn't
full-batch forensics), not every file that happened to share it. Every
caller (`mosaic`, single-file `clip`, `match`'s batched clip pass,
multi-file `clip`) gets the same unconditional clear; none of them relied
on a stale group_dir surviving into the next `parent_fid` iteration, so
this has no other behavioral effect.
