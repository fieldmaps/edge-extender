# 0032: clean's --snapping-distance auto pinned to SNAP_TOLERANCE

## Status

Accepted

## Context

ADR-0029 pinned `snapping_distance=SNAP_TOLERANCE` at `extend`/`stitch`'s
three internal `coverage_clean` call sites, but left `clean`'s user-facing
`--snapping-distance auto` mode on DuckDB's dynamic, extent-relative
auto-default (`extent_diameter / 1e8`, `docs/adr/0002`) as a separate,
unaddressed decision.

That default scales with the whole input file's bounding-box diagonal,
and `clean` runs on inputs ranging from a single admin1 territory to a
global mosaic, so the effective snapping distance swings by orders of
magnitude depending on what file happens to be passed in:

| Input scale | Extent diameter | Auto snapping distance | vs. SNAP_TOLERANCE (1e-8) |
| --- | --- | --- | --- |
| Small territory (e.g. `sxm_admin1`) | ~0.15° | 1.53e-9 | 6.5x too tight |
| Country (e.g. Chile, ~40° diameter) | ~40° | 4e-7 | 40x too loose |
| Global mosaic (~400° diameter) | ~400° | 4e-6 (~450m at the equator) | ~400x too loose |

Two distinct failure modes result: too tight on small files reproduces the
same detect-vs-fix mismatch ADR-0029 already fixed elsewhere (`detect`
flags violations at `SNAP_TOLERANCE`, but the auto snapping distance is too
small to actually close them); too loose on large files is worse, since
it's not a missed fix but active corruption, a ~450m snapping distance on
a global run would merge vertices belonging to genuinely distinct nearby
features (narrow straits, closely spaced islands, parallel boundary
segments), well past anything justifiable as floating-point noise.

## Decision

`clean/_03_clean.py`'s `auto` mode now resolves to `SNAP_TOLERANCE`
directly instead of `None` (which `coverage_clean()` maps to `-1`, keeping
GEOS's own computed default). This matches every other internal call site
in the pipeline and removes the input-size dependency entirely.

## Consequences

`clean`'s default snapping behavior is now identical to `extend`/`stitch`,
fixed at the same validated `1e-8°` regardless of input extent, instead of
silently diverging based on file size. A user who explicitly passes a
numeric `--snapping-distance` is unaffected.
