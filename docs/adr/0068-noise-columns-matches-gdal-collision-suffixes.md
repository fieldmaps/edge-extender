# 0068: noise-column exclusion matches a GDAL collision-suffixed name too

## Status

Accepted.

## Context

Real shapefiles can contain two fields that both reduce to the same GIS
bookkeeping name. Burundi's `COL_BURUNDI.shp` has both `Shape_Leng` and a
second, colliding shape-length field; GDAL's ESRI Shapefile (DBF) driver
caps field names at 10 characters total, so it truncates the second
field's base name and appends a disambiguating suffix, producing
`Shape_Le_1`. A separate upstream merge step produced `fid_1` the same
way, from GDAL's own synthesized `fid` colliding during a combine.
Neither exact-matches `core.constants.NOISE_COLUMNS`, so both survived
`map`'s exclusion and entered the candidate pool as ordinary source
columns, at the same row-level cardinality as the finest real admin code,
letting them falsely companion with it (the general, already-documented
risk in `docs/explanation/map.md`'s "not modeled in v1").

## Decision

`core.constants.is_noise_column(name)` replaces the direct
`name.lower() in NOISE_COLUMNS` check at both call sites (`map`,
`refactor`). A name matches if, case-insensitively, it exactly equals a
`NOISE_COLUMNS` entry; or, after stripping a trailing GDAL collision
suffix (`_\d+`), the remainder does; or the full name is exactly 10
characters (the DBF field-name limit) and the stripped remainder is a
prefix of some `NOISE_COLUMNS` entry (catching the truncate-and-suffix
case, e.g. `Shape_Le_1` -> `shape_le`, a prefix of `shape_length`).

The 10-character length gate is deliberate: without it, prefix-matching
alone risks a false positive against an unrelated short real column name.
Requiring the exact DBF limit as a precondition ties the heuristic to a
specific, verifiable file-format behavior instead of a loose guess.

## Consequences

`fid_1` and `Shape_Le_1` are excluded the same as their un-suffixed
counterparts, no longer appearing in a crosswalk at all. The fix is
general (any tool's numeric collision-suffix), not shapefile-specific,
except for the length-gated prefix branch, which only ever fires for a
10-character name. A field name genuinely truncated to a different total
length by some other driver's own limit isn't caught; not engineered
around further absent a concrete case.
