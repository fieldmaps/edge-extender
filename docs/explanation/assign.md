# Assign Explanation

`assign-many` and `assign-one` are two internal crosswalk strategies in
`core/assign/`, picked between by `match` (`assign-many`) and `mosaic`
(`assign-one`); neither is a standalone CLI/API tool. Both build a
`(child_fid, parent_fid)` pairing from a bbox-prefiltered, part-exploded
overlap-area join; they differ only in how that pairing gets finalized
once per-pair shared area is known. The right one to use is decided by
the input's geometry state, not by which tool you're eventually headed
toward:

- **`assign-many`**: each child decides independently which parent it
  overlaps most; one input file's children MAY scatter across **many**
  different parents. Correct for raw/unextended geometry, where a child
  can only ever overlap its true parent (there is no overshoot to
  misassign it).
- **`assign-one`**: every child in one input file is forced onto **one**
  shared parent, chosen by majority vote of that file's children. Needed
  for already-extended (post-`extend()`, overshoot) geometry, where a
  handful of border-crossing children could otherwise plurality-assign
  themselves to the wrong neighboring parent.

This is a decision-granularity distinction (per-child vs. per-file), not a
tool-of-origin one: `assign-many` is `match`'s assignment logic,
`assign-one` is `mosaic`'s.

## Modules

`core/assign/_01_inputs.py` loads the (possibly multi-file) child layer
and the single parent/clip layer raw via `core.io.read_and_reproject`,
neither coverage-checked nor -cleaned (consistent with `clip`/`stitch`;
these are all purely mechanical primitives). Every child row is tagged
with a `source_file` column recording the exact path it came from
(basename alone can't distinguish same-named files across directories).
Only `mosaic` calls it directly; `match` loads its own children via
`core.match._01_inputs` instead.

`_02_many.py` / `_02_one.py` hold the actual assignment logic (see
below); `match` calls `core.assign._02_many.main()`, `mosaic` calls
`core.assign._02_one.main()`, both directly on their own already-loaded
tables, the same pattern `core.match`/`core.change` use to call
`core.extend`'s stage functions directly rather than going through
`api.extend()`. Neither stage runs a coverage hard gate: an unclipped
crosswalk is expected to still overlap/gap between neighboring children,
that's `clip`'s and `stitch`'s job downstream.

## `_02_many`: largest-overlap assignment

Both layers are exploded into parts (`UNNEST(ST_Dump(geom))`) before
computing bbox candidates, a multi-part parent (a country with offshore
islands) would otherwise get one bbox spanning everything and defeat the
prefilter. Shared area per `(child, parent)` fid pair is summed across
every part-pair (a multi-part child can overlap a multi-part parent in
more than one place), ranked in an equal-area CRS (`EQUAL_AREA_CRS`)
rather than raw EPSG:4326 degree-area, which would bias plurality
assignment toward higher-latitude parents. Only the intersection geometry
is transformed, not the whole layer, to bound the cost.

```sql
ROW_NUMBER() OVER (PARTITION BY child_fid ORDER BY shared_area DESC, parent_fid ASC)
```

picks the plurality parent per child; ties break on the lowest parent fid.
Children with zero overlap with any parent are dropped with a logged
warning, not an error.

## `_02_one`: per-file majority-vote assignment

`_02_one` cannot use `_02_many`'s pairs join unmodified: it runs against
already-extended (often massively overshot) geometry, and a plain
`ST_Intersection`-based area-sum join against a huge single parent part
(e.g. a country-scale admin0 polygon) is exactly the failure mode `clip`
itself grid-tiles around. So `_02_one` builds its own pairs table
(`_build_pairs`), reusing `core.clip.subdivide_boundary` to tile any
parent part at or above `CLIP_TILE_MIN_VERTICES` before intersecting, the
same threshold and tiling logic `clip` uses.

For each `source_file`, `_02_one` counts how many of that file's children
intersect each candidate parent (a count of intersecting children, not
summed overlap area) and assigns every child in the file to whichever
parent wins that count, since a single file's children are always one
group. This guards against cross-country border overshoot misassigning a
file by per-child area alone; see `docs/adr/0019-mosaic-per-file-majority-vote.md`
for why a per-child rule isn't enough and what it was measured to break.

## Comparison

| | `assign-many` | `assign-one` |
| --- | --- | --- |
| Decision granularity | Per child | Per source file |
| Input assumption | Raw, unextended geometry | Already-extended (overshoot) geometry |
| Vote signal | N/A (each child stands alone) | Count of intersecting children per file |
| Misassignment risk | None from overshoot (there is none) | A file too small to form a real majority (single-child file, tied vote) |

## Caveats

**`assign-one` runs against overshoot geometry.** It never sees a child's
pre-extension footprint, only the already-extended geometry, so the bbox
prefilter is less selective than `assign-many`'s, and in principle the
per-child overlap signal underlying the vote could be skewed by a child
whose overshoot bulges further into a neighboring parent than into its
true one. The per-file majority vote mitigates this because a file's other,
unaffected children still outvote a single misbehaving one by count, but
a single-child file has no other vote to correct it, and a tied vote (e.g.
a two-child file split one-and-one between two parents) falls back to the
lower parent id rather than any geometric signal.
