# 0059: `map` leaves `target_column` empty unless a row resolves

## Status

Accepted. Changes the default `target_column` value for `ambiguous` and
`unmatched` rows from the source column's own name (the behavior since
ADR-0052) to empty.

## Context

`refactor` already drops any source column whose crosswalk
`target_column` is null/empty, and only renames a column with a non-empty
one. `map` was filling `target_column` with the column's own original
name for every `ambiguous`/`unmatched` row, so an unedited `map` output
fed straight into `refactor` silently kept every unresolved column under
its original name instead of dropping it, the opposite of what a blank
crosswalk cell should mean. A user's own hand-authored reference crosswalk
left `target_column` blank for every column that wasn't a resolved admin
level, expecting `map` to do the same.

## Decision

`target_column` is non-empty only for a `code`/`name` row. Every
`ambiguous`/`unmatched` row gets an empty `target_column`.

## Consequences

Running `refactor` on an unedited `map` crosswalk now drops every column
`map` didn't confidently resolve, rather than passing it through under its
original name. Keeping a column requires a human to fill in its
`target_column` by hand (its own name to keep it as-is, or a new name to
rename it), the same review step ADR-0052 always intended `map` to prompt
for, just enforced through `refactor`'s existing drop-on-empty rule
instead of a default `map` never should have supplied.
