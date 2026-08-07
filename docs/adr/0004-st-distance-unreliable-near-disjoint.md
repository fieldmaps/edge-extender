# 0004: ST_Distance is unreliable for two disjoint polygons at small separations

## Status

Accepted

## Context

Needed a way to check polygon disjointness/gap width.

## Decision

Confirmed `ST_Distance(GEOMETRY, GEOMETRY)` returns `0.0` for two clearly
separated polygons (~3cm apart) on the installed DuckDB version, while the
equivalent POINT/LINESTRING pair correctly returns the true distance. Use
`ST_XMin`/`ST_XMax`/`ST_YMin`/`ST_YMax` extent comparisons or
`ST_MaximumInscribedCircle` instead when checking polygon disjointness/gap
width.

## Consequences

Any new code checking polygon gap width or disjointness must avoid
`ST_Distance(GEOMETRY, GEOMETRY)` and use one of the alternatives above.
