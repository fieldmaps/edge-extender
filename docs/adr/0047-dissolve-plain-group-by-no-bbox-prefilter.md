# 0047: dissolve uses a plain GROUP BY, no bbox-prefiltered mitigation

## Status

Accepted.

## Context

`docs/adr/0001` documents that a single global `ST_Union_Agg` used as a
per-row `ST_Difference` operand OOMs at Chile scale (millions of vertices),
fixed in `core/extend/_05_merge.py` by exploding to bbox-tight parts and
gathering only nearby originals per row via a bbox-prefiltered self-join
before unioning. `dissolve`'s `_02_dissolve` stage also runs a
`GROUP BY`-scoped `ST_Union_Agg`, raising the question of whether it needs
the same mitigation.

## Decision

No mitigation was added. ADR-0001's OOM is specific to reusing a *global*
union repeatedly as a join/difference operand across every row of a table;
`dissolve` never does this; it runs one aggregate reduction per group,
each computed once, the same shape already used safely in
`core/extend/_04_voronoi.py:62` (`ST_Union_Agg(ST_MakeValid(geom)) ...
GROUP BY fid`), just generalized from a fixed `fid` key to caller-supplied
columns.

Benchmarked against Chile's real admin3-matched layer (345 features,
~824k vertices total, `hdx-scraper-cod-ab-global` portolan catalog,
`chl/latest/adm3/matched.parquet`) dissolved directly into 16 admin1
groups, the worst case in that dataset for single-group union size (one
group absorbing all of a region's islands): peak RSS 255 MB, 3.4s wall
time. This comfortably fits the 2-4 GB memory-constrained container target
in this repo's Deployment Targets, confirming the plain query is
sufficient without adopting `_05_merge.py`'s bbox-prefiltered complexity.

## Consequences

`core/dissolve/_02_dissolve.py` stays a single, simple query. If a future
dataset's per-group union proves too large for this approach (a country
with far more vertices concentrated in one group than Chile's), the same
bbox-prefiltered-per-part pattern `_05_merge.py` uses is the documented
fallback, adapted to group on arbitrary columns instead of `fid` — but
this is speculative until a real failure is observed, not a change made
preemptively here.
