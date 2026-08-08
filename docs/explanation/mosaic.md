# Mosaic Explanation

`mosaic` fits a **child** layer that is already the finished output of a
prior `extend()` run into a new/different **parent**/clip layer, without
re-running Voronoi extension. It exists because `match` redundantly redoes
extension for children that were already extended by an earlier pipeline
run: `match`'s own Colombia-scale profiling (see `docs/explanation/match.md`)
shows the `groups` stage (where per-parent extension happens) at 86% of
total wall time. If the geometry is already extended, only assignment,
clipping, and seam-closing need to happen.

## Pipeline

1. **`_01_inputs`**: loads and coverage-cleans both layers by delegating
   to `extend`'s own loader once per child file plus once for the parent
   (`{name}_child_01`, `{name}_parent_01`), identical to `match`'s inputs
   stage.
2. **`_02_assign`**: delegates to `match`'s own `_02_assign.py` for the
   per-child plurality-of-shared-area pass, then overrides it with a
   per-file majority vote (see below).
3. **`_03_clip`**: one `core.clip.clip_to_parent(..., assign_table=...)`
   call, running each distinct assigned parent fid's clip in its own
   spawned OS subprocess, grid-tiling that parent's boundary (adaptively,
   see below) before intersecting. Raises if the result is empty.
4. **`_04_merge`**: the same whole-table `ST_CoverageClean` pass as
   `match`'s `_04_merge.py`, closing seams between children clipped to
   adjacent parents.
5. **`_05_outputs`**: the same `check_overlaps`/`check_gaps` hard gate,
   an issues report listing only unassigned children (no dropped-group
   kind, since there are no groups), and export.

## Multi-file children

Unlike every other tool here, the child role MAY span multiple files in one
call (the portolan catalog stores one `extended.parquet` per country, never
pre-combined); the parent/clip layer stays single-file. `_01_inputs`
loads each path independently through `extend`'s loader, tags each with its
own full path as a `source_file` column (basename alone can't distinguish
same-named files across directories), then combines with `UNION ALL BY
NAME` rather than plain `UNION ALL` so files with differing attribute
schemas (e.g. different countries' original admin-boundary columns) fill
missing columns with NULL instead of erroring. `fid` is renumbered fresh
after the union. `output_path` MUST be given explicitly whenever multiple
paths are passed, since there's no single filename to default one from.

## Per-file majority-vote assignment

`_02_assign` runs match's per-child plurality first, then always overrides
it: for each `source_file`, it counts how many of that file's children
intersect each candidate parent (from `_02_pairs`, a count of intersecting
children, not summed overlap area) and reassigns every child in the file to
whichever parent wins that count, since a single file's children are always
one group, whether the call combines one file or many. Confirmed
empirically this project: combining 8 West Africa countries'
`extended.parquet` layers found 19 real coverage gaps (up to 0.57 sq
degrees, in Togo) from individual border-adjacent admin2 units whose
overshoot gave a neighboring country's parent more overlap *area* than
their own (e.g. a Côte d'Ivoire unit landing on Ghana). Per-child plurality
alone can't tell "genuine outlier"
from "truly belongs to the neighbor"; per-file majority vote can, because a
country's interior units (unaffected by border overshoot) still
overwhelmingly vote for their true parent by count.

## Why `core/clip.py` is a neutral leaf

`match`'s original `_clip.py::clip_to_parent_geom` only ever clipped every
row of one group against one parent per call. `mosaic` needs the same
`ST_Intersection`-drop-empty logic, but against a different parent per row,
selected via an assign table. Rather than duplicate the SQL or have
`mosaic` import from `core.match`, the clip logic was generalized into
`core/clip.py` and both tools now call it: `assign_table=None` preserves
match's original one-parent-per-call behavior byte-for-byte (already
running inside `match`'s own per-group subprocess, so no further isolation
needed); `assign_table=<name>` is mosaic's many-parents-per-call mode, each
parent fid clipped in its own spawned subprocess with its boundary
adaptively grid-tiled first (see Caveats, `docs/adr/0015`, `docs/adr/0016`,
`docs/adr/0017`). This
makes `core.clip` a fifth neutral leaf module alongside
`core.constants`/`core.coverage`/`core.io`/`core.duckdb_utils`, since two
tools now depend on it and it holds no tool-specific state.

## Why `_02_assign` is a delegate, not a leaf

Unlike clip, assignment logic wasn't generalized. `mosaic` imports
`core.match._02_assign` directly, the same way `core.match`/`core.change`
already import `core.extend`'s stage functions for reused pipeline logic.
The per-child plurality-of-shared-area algorithm is identical for both
tools, just called against `mosaic`'s own
`{name}_child_01`/`{name}_parent_01` tables; the per-file majority-vote
override on top of it is `mosaic`-specific, since `match` has no
`source_file` concept to vote by.

## match vs. mosaic

| | `match` | `mosaic` |
| --- | --- | --- |
| Input assumption | Child layer is raw, unextended | Child layer is already a finished `extend()` output |
| Assign runs against | Original (tight) geometry | Already-extended (overshoot) geometry |
| Cost driver | Per-group Voronoi extension (~86% of wall time) | Assign + clip + merge only, no extension |
| Isolation | Per-group subprocess (GEOS heap-leak workaround) | Per-parent-fid subprocess, boundary adaptively grid-tiled (`docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`) |
| When to use | Child layer hasn't been extended yet | Reusing pre-extended layers against a new/different parent |

## Caveats

**Assign runs against overshoot geometry.** `mosaic` never sees the
child's pre-extension footprint, only the already-extended (often
massively overshot; see below) geometry. This makes the assign step's bbox
prefilter less selective than `match`'s, and in principle the
plurality-of-shared-area rule could pick the wrong parent for a child whose
overshoot happens to bulge further into a neighboring parent than into its
"true" one. This cannot happen in `match`, where assign always runs on
tight, pre-extension geometry. The per-file majority vote (above) mitigates
this for the case it was built for, cross-country border overshoot,
because a file's other, unaffected children still outvote a single
misbehaving one by count. The residual risk is a file with too few children
to form a real majority: a single-child file has no other vote to correct
it, and a tied vote (e.g. a two-child file split one-and-one between two
parents) falls back to the lower parent id rather than any geometric
signal. Confirmed empirically this project: Chile admin3's
`extended.parquet` is roughly 200x the area of the original layer, with a
bounding box spanning most of the South Pacific. An overshoot of that
scale is the normal, intended output of `extend()`, not a data error, but
it means `mosaic`'s assign step is working with far less selective
geometry than `match`'s ever is.

**Clip runs one parent fid at a time, each in its own subprocess with its
boundary adaptively grid-tiled.** A single query intersecting every assigned
child against every parent's full geometry at once, and later a per-parent
loop within one process, both OOM'd at continent scale. Below
`CLIP_TILE_MIN_VERTICES` a parent is clipped directly with no subdivision;
above it, the tile size is solved from that parent's own vertex density
rather than a fixed constant. See `docs/adr/0015` (per-parent subprocess
isolation), `docs/adr/0016` (grid-tiling a large parent's boundary before
intersecting), and `docs/adr/0017` (adaptive threshold/cell size) for the
full empirical detail.

**Cross-provenance seam risk.** `docs/explanation/match.md` documents genuine
(non-float-noise) seam disagreements up to ~645m between two groups
extended moments apart by the *same* `match()` run. `mosaic`'s children can
come from wholly different tool versions or vintages (the portolan
catalog has per-country pipeline drift, e.g. `phl` has v01 through v03),
with no guarantee that any two `extended.parquet` files being combined into
one `mosaic()` input were even produced by compatible `extend()` versions
(only empirically-confirmed schema/CRS compatibility). The `check_gaps`/
`check_overlaps` hard gate still runs and raises before export, but a
multi-provenance mosaic run should have its parent-parent boundaries
spot-checked visually (e.g. via the `geo-preview` skill), not just trusted
because the hard gate passed. Use the output's `source_file` column to
find which two files actually meet at a flagged seam.
