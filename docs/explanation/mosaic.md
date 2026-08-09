# Mosaic Explanation

`mosaic` fits a **child** layer that is already the finished output of a
prior `extend()` run into a new/different **parent**/clip layer, without
re-running Voronoi extension. It exists because `match` redundantly redoes
extension for children that were already extended by an earlier pipeline
run: `match`'s own Colombia-scale profiling (see `docs/explanation/match.md`)
shows the `groups` stage (where per-parent extension happens) at ~85% of
total wall time. If the geometry is already extended, only assignment,
clipping, and seam-closing need to happen: the same three primitives
`assign`, `clip`, and `stitch` expose standalone (see their own explanation
docs); `mosaic` is a thin wrapper chaining `assign-one` → `clip` → `stitch`.

## Pipeline

1. **`_01_inputs`**: loads both layers raw via `core.io.read_and_reproject`,
   once per child file plus once for the parent (`{name}_child_01`,
   `{name}_parent_01`). Neither side is coverage-checked or -cleaned; see
   "Why neither input is coverage pre-checked" below.
2. **assign**: calls `core.assign._02_one.main()` directly, the same
   per-file majority-vote pairing `assign-one` exposes standalone, see
   `docs/explanation/assign.md`. Also narrows `{name}_parent_01` down to
   only the parent fids any child was actually assigned to, before clip
   runs.
3. **`_03_clip`**: a thin wrapper joining `parent_fid` onto
   `{name}_child_01` from `{name}_02_assign`, then calling
   `core.clip.main()`, the same per-`parent_fid`-subprocess, adaptively
   grid-tiled clip `clip` exposes standalone, see `docs/explanation/clip.md`.
4. **`_04_stitch`**: calls `core.stitch._02_clean.main()` directly, the
   same whole-table `ST_CoverageClean` pass `stitch` exposes standalone,
   see `docs/explanation/stitch.md`.
5. **`_05_outputs`**: the same `check_overlaps`/`check_gaps` hard gate,
   an issues report listing only unassigned children (no dropped-group
   kind, since there are no groups), and export.

## Multi-file children

Unlike every other tool here, the child role MAY span multiple files in one
call (the portolan catalog stores one `extended.parquet` per country, never
pre-combined); the parent/clip layer stays single-file. `_01_inputs`
loads each path independently via `core.io.read_and_reproject`, tags each
with its own full path as a `source_file` column (basename alone can't
distinguish same-named files across directories), then combines with `UNION ALL BY
NAME` rather than plain `UNION ALL` so files with differing attribute
schemas (e.g. different countries' original admin-boundary columns) fill
missing columns with NULL instead of erroring. `fid` is renumbered fresh
after the union. `output_path` MUST be given explicitly whenever multiple
paths are passed, since there's no single filename to default one from.

## Why neither input is coverage pre-checked

Neither the parent nor the child layer is checked or cleaned for coverage
violations before assign/clip runs (see ADR-0018). `_05_outputs.py`'s hard
`check_overlaps`/`check_gaps` gate on the final stitched output already
guarantees correctness regardless: there is no path where a dirty parent
or child silently reaches export undetected, only a loud failure. The
child layer is additionally assumed to already be a finished `extend()`
output, which `mosaic` never re-verifies.

## match vs. mosaic

| | `match` | `mosaic` |
| --- | --- | --- |
| Input assumption | Child layer is raw, unextended | Child layer is already a finished `extend()` output |
| Assign strategy | `assign-many` (per-child plurality) | `assign-one` (per-file majority vote) |
| Cost driver | Per-group Voronoi extension (~85% of wall time) | Assign + clip + stitch only, no extension |
| Isolation | Two subprocess generations: per-group `extend`, then batched per-`parent_fid` `clip` (`docs/adr/0020`) | Per-`parent_fid` subprocess only, boundary adaptively grid-tiled (`docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`) |
| When to use | Child layer hasn't been extended yet | Reusing pre-extended layers against a new/different parent |

## Caveats

**Assign runs against overshoot geometry.** See `docs/explanation/assign.md`'s
Caveats section for the full detail on `assign-one`'s per-file majority vote
and its residual risk (a file too small to form a real majority).

**Clip runs one parent fid at a time, each in its own subprocess with its
boundary adaptively grid-tiled.** See `docs/explanation/clip.md` for the
full detail.

**Cross-provenance seam risk.** `docs/explanation/stitch.md` documents
genuine (non-float-noise) seam disagreements up to ~645m between two tiles
computed independently. `mosaic`'s children can come from wholly different
tool versions or vintages (the portolan catalog has per-country pipeline
drift, e.g. `phl` has v01 through v03), with no guarantee that any two
`extended.parquet` files being combined into one `mosaic()` input were even
produced by compatible `extend()` versions (only empirically-confirmed
schema/CRS compatibility). The `check_gaps`/`check_overlaps` hard gate
still runs and raises before export, but a multi-provenance mosaic run
should have its parent-parent boundaries spot-checked visually (e.g. via
the `geo-preview` skill), not just trusted because the hard gate passed.
Use the output's `source_file` column to find which two files actually
meet at a flagged seam.
