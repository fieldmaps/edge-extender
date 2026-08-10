# 0034: clean's --snapping-distance no longer accepts the literal 'auto'

## Status

Accepted

## Context

ADR-0032 pinned `--snapping-distance auto` to `SNAP_TOLERANCE`. ADR-0033
then demoted `--maximum-gap-width`'s equivalent default the same way, but
went further: the noise-floor behavior there is reachable only by omitting
the flag, the literal string `"auto"` itself is rejected, since no name for
"always exactly `SNAP_TOLERANCE`" reads well as a peer alongside a mode
like `thin` that actually computes something from the data.

The same reasoning applies to `--snapping-distance`: its only other
possible value is a raw number, there was never a second named mode to be
a peer of. Leaving `"auto"` valid there while rejecting it for
`--maximum-gap-width` would be an inconsistency with no principled reason
behind it, both flags reach the same fixed `SNAP_TOLERANCE` constant by
omission; only one of them should treat that as a nameable choice.

## Decision

`--snapping-distance auto` (and `api.clean.clean()`'s `snapping_distance="auto"`)
now raises `ValueError`, matching `--maximum-gap-width`'s `"auto"`
rejection. The default is reached only by omitting the flag (or passing
`None` to the API function directly). `api.clean.clean()`'s
`snapping_distance` parameter changed type from `str = "auto"` to
`str | None = None`.

## Consequences

Both `clean` fix-width flags now follow one consistent rule: a named mode
is either a real, data-dependent computation (`--maximum-gap-width thin`)
or a literal number, never a name for a fixed constant. Any existing
caller passing the literal string `"auto"` to either flag now gets a
`ValueError` instead of the old (already-`SNAP_TOLERANCE`) behavior.
