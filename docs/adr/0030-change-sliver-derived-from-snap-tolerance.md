# 0030: change's INTERSECTION_SLIVER_DEG2 derived from SNAP_TOLERANCE**2, not an independent literal

## Status

Accepted

## Context

`INTERSECTION_SLIVER_DEG2 = 1e-12` (deg², ported as-is from topo-tools-js)
was commented `"~1cm^2"`. Verified: `1e-12 deg² ≈ 124 cm²` at the equator
(`111,320² m/deg² × 1e-12`), ~100x larger than the comment claimed, too
big a gap to be a latitude effect.

## Decision

Derive it as `SNAP_TOLERANCE**2` instead, so the codebase has one grounded
noise-floor constant instead of two independently-tuned ones. Verified with
`uv run lint-imports` (import-linter contracts still pass, `change`
importing `core.constants` is an allowed neutral-leaf import) and the full
test suite (115/115 passing, including all 13 `change` tests).

## Consequences

Open question, not resolved in this session: whether this makes `change`'s
sliver filter too strict for real independently-digitized boundary pairs.
The synthetic test fixtures don't exercise real digitizing noise, and no
real old/new boundary pair was available to validate against at scale.
