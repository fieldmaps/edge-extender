# 0031: Considered and rejected a two-constant resolution/tolerance split modeled on ArcGIS

## Status

Rejected

## Context

Researched whether `SNAP_TOLERANCE` should split into a finer
"snap/resolution" constant (for `ST_Snap`/`snapping_distance` call sites)
and a coarser "tolerance/detection" constant (for
`has_coverage_violations`/`gap_maximum_width`/`INTERSECTION_SLIVER_DEG2`),
motivated by ArcGIS's confirmed default pairing: XY Resolution `1e-9°`, XY
Tolerance `0.001m` (≈9e-9° at the equator, ~10x resolution), with a
documented hard floor of 2x (ArcGIS Pro error 130020, "must be at least
twice as large"), both facts verified directly against `pro.arcgis.com`'s
own docs, not from memory.

## Decision

Rejected, after closer reading of what ArcGIS's two parameters actually do.
ArcGIS's *tolerance*, not resolution, is what performs vertex merging ("if
one vertex... is within the tolerance of another, both are moved to a new
location"); *resolution* is an unconditional coordinate-storage rounding
grid applied to every coordinate regardless of any topological operation,
with no equivalent anywhere in this pipeline (DuckDB stores full double
precision throughout; nothing here does `ST_ReducePrecision`/
`ST_SnapToGrid`-style global quantization). Every current `SNAP_TOLERANCE`
call site, including `ST_Snap`/`snapping_distance`, which a first pass
mis-mapped onto ArcGIS's resolution role, is actually doing ArcGIS's
*tolerance* job. A single shared value is therefore the more faithful match
to ArcGIS's own model, not a two-value split.

Also noted as a supporting, independent argument: no positive evidence
exists that a 10x-finer value would still reliably close real GEOS
crossing-point jitter in `ST_Snap`/`snapping_distance`
(`docs/explanation/topology.md`'s sweep test and this session's Chile
`_05_tmp3` measurement both validate `1e-8` specifically, not a finer
value).

Cross-tool comparison, also gathered in the same investigation: JTS's own
default overlay snap tolerance (`GeometrySnapper.java`,
`SNAP_PRECISION_FACTOR = 1e-9`, applied as `min(width, height) * 1e-9`) and
DuckDB's own `ST_CoverageClean` auto-`snapping_distance`
(`extent_diameter / 1e8`, `docs/adr/0002-gap-maximum-width-no-native-default.md`)
both scale *relative to each geometry's own extent* rather than using a
fixed absolute value; neither matches ArcGIS's fixed-constant approach.

## Consequences

`SNAP_TOLERANCE` stays a single constant. This project's fixed `1e-8°`
remains a deliberate, project-specific choice validated on its own merits
(the `topology.md` sweep test), not something "industry standard" tools
converge on.
