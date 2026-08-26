# 0090: Bbox-prefilter `_03_points.py`'s shared-boundary-zone difference

## Status

Accepted

## Context

`idn_admin4` (81,912 fids) and `phl_admin4` (42,048 fids) OOM'd/stalled in
`edge-extend`. `_03_points.py`'s `_03b` construction differenced every fid
individually against `_03a`, a single-row, whole-file `ST_Union_Agg` of
every boundary point in the layer, the same anti-pattern `_05_merge.py`
already avoids per `docs/adr/0001`, never guarded here. Cost scales with
fid count, not `DISTANCE`: `idn_admin4` hit the identical 12.7GiB OOM at
every one of `attempt.py`'s 6 retried resampling distances; `phl_admin4`
cost 250-260s/8-9GB peak RSS on each of 3 retries before falling through
to `MAX_POINTS` and retrying at a doubled distance.

## Decision

Mirror `_05_merge.py`'s bbox-prefiltered-local-union pattern: `_03a` is now
a per-fid, bbox-tagged buffered boundary zone (built once in
`build_segments()`, hoisted out of the retry loop since it never depended
on `distance`) instead of one global blob; `_03b` differences each fid
against a bbox-prefiltered local union of nearby fids' zones via a LEFT
JOIN (a fid with zero locally-overlapping neighbors keeps its own geometry
via a `CASE WHEN n.geom IS NULL` fallback, an INNER JOIN would silently
drop it), never the global operand.

Granularity is whole-fid bbox, matching `_02_lines.py`'s precedent
(`docs/adr/0001`), not `_05_merge.py`'s part-exploded one: the operation
here (difference each fid against everyone else's nearby boundary) is the
same shape of problem `_02_lines.py` already solved this way.

Two new guards close the correctness gap this rewrite could otherwise
open silently:

- `_03_points.py` raises if the LEFT JOIN differencing drops any fid
  entirely (`_03_tmp4`'s fid set minus `_03b`'s).
- `_06_outputs.py` raises if the final extended geometry no longer covers
  its original footprint per fid, via `ST_Covers(ST_Buffer(e.geom,
  SNAP_TOLERANCE), o.geom)`. The `SNAP_TOLERANCE` buffer absorbs GEOS's
  own floating-point noise (empirically ~1e-18 to 1e-19 sq-degrees on real
  `idn_admin4` output, vs. a median fid area of 4.6e-4) without masking
  real erosion; benchmarked at 9.08s against an area-based
  `ST_Difference`+`ST_Area` alternative's 54-62s on the same file, and the
  area-based check still produced 313 false positives at a naive `> 0`
  threshold, so it's both slower and less correct.

## Consequences

`idn_admin4`, `phl_admin4`, and `chl_admin3` (the whole-fid-bbox
regression check, per `docs/adr/0001`'s precedent) all complete cleanly
from real portolan-catalog input with no OOM, no repeated retry cost, and
no missing-fid or erosion guard failures.
