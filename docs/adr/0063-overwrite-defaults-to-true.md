# 0063: `overwrite` defaults to `True` across every tool

## Status

Accepted.

## Context

Every tool's `overwrite` kwarg defaulted to `False`: an existing output
path raised `FileExistsError` unless the caller passed `overwrite=True`
(CLI: `--overwrite`). Re-running a tool against the same output (the
normal iterate-on-a-crosswalk or rerun-after-a-fix workflow) required
remembering that flag every time, and the error message was the only
feedback either way. User direction: make overwriting the default,
but keep a way to get the old error back, and keep the check itself in
one place instead of duplicated per tool so a future change to this
behavior doesn't need a sweep across a dozen files.

## Decision

1. Every `api.*()` function's `overwrite` kwarg defaults to `True`. When
   an output path exists and `overwrite` is `True`, the call logs
   `"overwriting existing output: {path}"` (via `logger.info`) and
   proceeds; when `overwrite` is `False`, it still raises
   `FileExistsError("output already exists: {path}")`.
2. This check is centralized in `core.io.check_overwrite(path, *,
   overwrite)`; every `api.*()` function calls it once per output path
   instead of an inline `if path.exists() and not overwrite: raise`.
3. The CLI's `--overwrite` option is a value-taking boolean
   (`type=bool, default=True`), not an `is_flag` toggle, so restoring the
   old error behavior is `--overwrite=false` (or `OVERWRITE=false`), not
   a second `--no-overwrite` flag name. Click's built-in `BOOL` type
   already accepts `false`/`False`/`no`/`off`/`0` (and their `true`-side
   opposites) case-insensitively, so no custom parsing was needed.

## Consequences

Rerunning a tool against the same output path just works; a reviewer
sees the overwrite in the log instead of silence. Anyone who wants the
old safety net passes `--overwrite=false` explicitly. A future change to
this behavior (a different message, a confirmation step, a dry-run mode)
only touches `core.io.check_overwrite()`, not every tool's `api.*()`
function.
