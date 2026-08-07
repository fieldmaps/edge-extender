# 0001: Avoid a global ST_Union_Agg as a per-row join/difference operand

## Status

Accepted

## Context

At Chile scale (`chl_admin3`), a single global `ST_Union_Agg` of `_01` can hold
millions of vertices. Using it as an operand against every fid individually
in `_05_merge.py` made GEOS pay that cost on every row and OOM'd outright,
confirmed during development of `_05_merge.py`.

## Decision

Use a bbox-prefiltered join against nearby originals instead
(`_05_merge.py`'s `_05_tmp1`/`_05_tmp2`), exploding multipolygon fids into
parts first — a whole-fid bbox can span mainland-to-remote-island and defeat
the prefilter.

`_02_lines.py`'s neighbor-union self-join deliberately does **not** do the
same part-exploding: it joins on whole-fid bboxes. Exploding it into
per-part bboxes looks like the same fix but isn't — it helps files with many
fids that each have a few widely-scattered parts (e.g. `idn_admin3`) but
badly regresses files with one fid made of thousands of tightly-clustered
parts (e.g. `chl_admin3` has a single fid with 3,796 parts), multiplying
self-join row count far more than the tighter bboxes save.

## Consequences

Confirmed empirically: Chile is 3.3GB peak with whole-fid bboxes vs. OOM at
10GB+ with per-part bboxes. `_05_merge.py` and `_02_lines.py` use different
bbox granularities on purpose — don't "fix" one to match the other.
