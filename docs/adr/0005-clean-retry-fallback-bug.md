# 0005: clean's per-detection-kind retry didn't fall back to empty on a double failure

## Status

Accepted

## Context

`clean/_02_issues.py`'s module docstring promised each detection kind is
"retried once at reduced precision, then falls back to an empty result
(logged) rather than raising." `_run_with_retry` only logged on the second
failure — it never created the temp table, so a double failure left it
entirely missing and crashed `main()`'s downstream `UNION ALL` with a
binder/catalog error instead of degrading gracefully.

## Decision

Fixed by passing each call site an explicit `empty_sql` that
`_run_with_retry` executes when both attempts fail, so the target table
always exists afterward.

## Consequences

The "one kind failing shouldn't block the others" contract is now actually
honored. Any new call site of `_run_with_retry` must supply `empty_sql`.
