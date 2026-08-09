# 0006: Sliver detection/fixing was removed

## Status

Accepted

## Context

Earlier versions of `clean` also detected (but never auto-fixed) slivers,
near-miss boundary mismatches, via `ST_CoverageInvalidEdges_Agg(geom,
tolerance)`.

## Decision

Removed entirely for two reasons:

- **Never fixable in the first place.** Auto-snapping a near-miss sliver
  closed requires widening `ST_CoverageClean`'s `snapping_distance`
  parameter, which re-nodes the **whole** coverage, not just the defect
  site, silently perturbing unrelated, already-correct geometry elsewhere
  in the file. Unacceptable for something running unattended in a batch
  pipeline; the JS sister app reversed the same way early in its own
  history (commit `9e57932`, "slivers detection-only; remove snap and
  Changes feature").
- **Detection itself was not reliable enough to keep as report-only,
  either.** The gap/overlap-subtraction step in the detection query (buffer
  + cross join + `ST_Difference` against unioned blobs) reproducibly
  triggered a DuckDB out-of-memory error on real data, confirmed on
  Angola admin1 (`hdx-cod-ab-ai`'s `ago_admin1.parquet`, only 21 fids/490K
  vertices, nowhere near the scale where `extend`'s known memory ceilings
  kick in). Disabled by default (`--sliver-tolerance 0`) for this reason
  before removal.

## Consequences

Any near-miss boundary mismatch is now an upstream data-quality issue,
outside this tool's scope: fixing it (re-digitizing the source, or manual
editing in QGIS/ArcGIS) remains a human decision, same as before, just
without an automated detector flagging candidates.
