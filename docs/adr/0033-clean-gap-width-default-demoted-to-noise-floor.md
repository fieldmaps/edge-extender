# 0033: clean's default gap-fill width demoted from shape-based to SNAP_TOLERANCE

## Status

Accepted

## Context

`clean`'s previous default gap-fill mode filled any gap whose *shape*
looked like a digitization sliver (Polsby-Popper compactness `<=
DEFAULT_THINNESS_RATIO`), computing a single width from the widest such
gap and passing that width straight to `ST_CoverageClean`. But
`gap_maximum_width` is a pure width cutoff with no shape concept of its
own: it applies that one computed width to every gap in the table, not
per-polygon. `docs/explanation/clean.md` already documented this as a
"known, accepted imprecision" ("a non-thin gap narrower than the widest
thin gap would also get swept in"), but on reflection this is too
aggressive for real-world use as a *default*: a genuinely compact real
feature (a small pond, a narrow strait) narrower than whatever thin sliver
happens to be the widest one in the same file gets silently swallowed too,
with no per-polygon shape check protecting it.

Separately verified before making this change: `snapping_distance` and
`gap_maximum_width` are independent GEOS mechanisms, not overlapping ones.
A direct test (two polygons separated by an enclosed `SNAP_TOLERANCE`-wide
hole) confirmed `snapping_distance` alone, at any value, never closes a
genuinely enclosed interior gap; only `gap_maximum_width` does. So pinning
`--snapping-distance auto` to `SNAP_TOLERANCE` (`docs/adr/0032`) doesn't
make a `SNAP_TOLERANCE`-based gap-width default redundant, they fix
different defect classes (edge mismatches vs. enclosed holes).

## Decision

The default gap-fill behavior (reached only by omitting
`--maximum-gap-width`, not a named mode) now fills a gap only if its width
is at or below `SNAP_TOLERANCE`, the same fixed noise floor validated
elsewhere in the pipeline (`docs/adr/0029`). This is unconditionally safe
regardless of shape, since anything that small is floating-point noise by
construction, not a real feature.

The previous shape-based logic is still useful for users who want it, so
it's kept, renamed from `auto` to `thin`, no longer the default. The
literal string `"auto"` is rejected (`ValueError`), not accepted as a
silent synonym: the noise-floor default is deliberately reachable only by
omission, not by a name, since no name for "always exactly
`SNAP_TOLERANCE`" tested well as a peer alongside `thin`/`all` (`auto`
implied data-adaptive computation it doesn't do; `noise`/`min` were both
considered and rejected as added vocabulary for what should just be
"the default").

## Consequences

`clean`'s out-of-the-box behavior is now conservative: only true
noise-scale gaps get auto-fixed, everything else is reported but left for
review unless a user explicitly asks for `thin`, `all`, or a numeric
width. `api.clean.clean()`'s `maximum_gap_width` parameter changed type
from `str = "auto"` to `str | None = None`; any caller passing the literal
string `"auto"` now gets a `ValueError` instead of the old shape-based
behavior.
