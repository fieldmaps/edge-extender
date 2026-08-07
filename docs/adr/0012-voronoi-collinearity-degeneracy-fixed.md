# 0012: Voronoi collinearity degeneracy fixed via a per-segment interpolation cap

## Status

Accepted

## Context

A full-corpus run showed per-file durations uncorrelated with file size or
boundary length — Chile and Indonesia (the largest exterior boundaries)
were comparatively fast, while Chad, Mali, Niger, and Algeria (much
smaller, sparser boundaries) were the slowest. Profiling Chad in isolation
found the cost concentrated entirely in `_04_voronoi.py`'s
`ST_VoronoiDiagram` call: ~300s at only ~600MB RSS — a low-memory,
high-time signature distinct from every other slow file, which were all
memory-bound instead. The working theory: Chad's admin2 boundaries are
long, straight desert lines: fixed-interval interpolation along them
produces long runs of exactly collinear points, a known pathological input
for Voronoi-diagram algorithms independent of point count.

## Decision

`_03_points.py` decomposes each boundary line into its own real
vertex-to-vertex segments (no geometry alteration) and caps interpolation
at `MAX_POINTS_PER_SEGMENT = 100` points per segment, bounding the largest
exactly-collinear point cluster fed to `ST_VoronoiDiagram` independent of
that segment's raw length. `100` was chosen as the smallest of several
tested values — `ST_VoronoiDiagram` time on the reproduction file scaled
worse than linearly with this constant — with zero measured downside on
files that don't hit the cap. Chad's Voronoi step dropped from ~300s to
~1s; Algeria, suspected to share the same mechanism, was confirmed and
fixed the same way.

## Consequences

Three implementation bugs surfaced while building this and were fixed
alongside it: `ST_PointN`-based segment decomposition is O(n²) and OOMs at
scale (replaced with `ST_Points`/`ST_Dump`/`LAG()`); differencing generated
points against the shared-boundary zone per segment instead of per fid
caused a large call-count blowup (fixed by aggregating to one multipoint
per fid first); unconditionally guaranteeing one point per real segment
created a floor equal to a file's raw vertex count (fixed by only capping
segments that are actually long, falling back to the original whole-line
resampling formula otherwise).
