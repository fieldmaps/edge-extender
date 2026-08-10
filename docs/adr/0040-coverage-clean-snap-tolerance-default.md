# 0040: coverage_clean's gap_maximum_width/snapping_distance default to SNAP_TOLERANCE

## Status

Accepted.

## Context

`coverage_clean()` (`core/coverage.py`) has four call sites. Three,
`extend/_01_inputs.py`, `extend/_05_merge.py`, and `stitch/_02_clean.py`,
pass the identical literal `gap_maximum_width=SNAP_TOLERANCE,
snapping_distance=SNAP_TOLERANCE` every time: each is closing seam-scale
noise on a layer where, by construction, there's no real feature left to
protect (see the comment in `_05_merge.py`, `docs/explanation/stitch.md`).
The fourth, `clean/_03_clean.py`, is the genuine outlier: it computes both
values itself per call (`_resolve_gap_maximum_width_deg()`'s
`auto`/`all`/`thin`/explicit modes, and `snapping_distance_deg` from its
own `--snapping-distance` flag), including passing literal `None` for
`gap_maximum_width` when no gap was detected, deliberately leaving
`ST_CoverageClean`'s gap-fill member at GEOS's own hardcoded `0.0`
(no gap-filling attempted; see `docs/adr/0002`).

`gap_maximum_width` currently has no default at all, every call site is
forced to pass it explicitly. `snapping_distance` defaults to `None`,
mapping to DuckDB's own extent-relative auto-default
(`extent_diameter / 1e8`, see `docs/adr/0002`), but no call site has ever
relied on that: all four pass an explicit float, and the project already
treats that auto-default as disfavored for this codebase (`clean`'s own
`--snapping-distance` pins to `SNAP_TOLERANCE` rather than leaving it
unset). Same shape as `has_gaps`/`check_valid_topology` before ADR-0039:
one literal value repeated at most call sites, with one tool alone
computing something different.

## Decision

`coverage_clean()` now defaults both `gap_maximum_width` and
`snapping_distance` to `SNAP_TOLERANCE`, keeping the `float | None` type
on both (`clean` still needs to pass literal `None` explicitly for its
no-gap-detected case). `extend/_01_inputs.py`, `extend/_05_merge.py`, and
`stitch/_02_clean.py` drop their now-redundant explicit arguments,
relying on the default; `extend/_01_inputs.py` loses its only remaining
use of the `SNAP_TOLERANCE` import as a result. `clean/_03_clean.py` is
unaffected: it always passes its own resolved `gap_maximum_width_deg`/
`snapping_distance_deg`, never relying on the default.

`fids` is untouched (stays required, no default): all four call sites
pass `fids=None`, but it's a row-subset selector, not a tolerance value,
and changing it wasn't asked for.

## Consequences

A future caller of `coverage_clean()` that omits both arguments now gets
the same noise-level-seam-only behavior `extend`/`stitch` already rely on
explicitly, rather than a `TypeError` (for the previously-required
`gap_maximum_width`) or DuckDB's extent-relative auto-snap (for the
previously-`None`-defaulted `snapping_distance`). `clean`'s explicit
`None` for `gap_maximum_width` when no gap was detected keeps meaning
exactly what it meant before (GEOS's native no-fill state), unaffected by
the new default.
