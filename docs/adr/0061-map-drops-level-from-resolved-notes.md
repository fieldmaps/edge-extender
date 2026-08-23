# 0061: `map` drops level from a resolved row's `note`

## Status

Accepted.

## Context

ADR-0060 put a resolved row's level in `note` (e.g. `"code, level 1"`).
For a `code`/`name` row, `target_column` already names the level (e.g.
`adm4_pcode`, `adm4_name`), so restating it in `note` is redundant; a
real run's crosswalk review flagged this as unnecessary noise. An
`ambiguous` row has no `target_column` (it's left empty until a human
resolves it), so its level isn't available anywhere else.

## Decision

A `code`/`name` row's `note` starts with its tier alone (`"code"`,
`"name"`); an `ambiguous` row's `note` keeps the tier-plus-level form
from ADR-0060 (`"ambiguous, level 1; ..."`). The one-short-clause rule
from ADR-0060 is otherwise unchanged.

## Consequences

A reviewer scanning a resolved row reads the level off `target_column`
instead of a duplicated `note`; an `ambiguous` row still states its
level since nothing else on the row does.
