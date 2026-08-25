# Mosaic Explanation

`edge-mosaic` fits a **child** layer that is already the finished output of a
prior `edge_extend()` run into a new/different **parent**/clip layer, without
re-running Voronoi extension. It exists because `edge-match` redundantly redoes
extension for children that were already extended by an earlier pipeline
run: `edge-match`'s own Colombia-scale profiling (see `docs/explanation/edge_match.md`)
shows the `groups` stage (where per-parent extension happens) at ~85% of
total wall time. If the geometry is already extended, only assignment,
clipping, and seam-closing need to happen: the same three primitives
`assign`, `edge-clip`, and `edge-stitch` expose standalone (see their own explanation
docs); `edge-mosaic` is a thin wrapper chaining `assign-one` → `edge-clip` → `edge-stitch`.

## Pipeline

1. **`_01_inputs`**: loads both layers raw via `core.io.read_and_reproject`,
   once per child file plus once for the parent (`{name}_child_01`,
   `{name}_parent_01`). Neither side is coverage-checked or -cleaned; see
   "Why neither input is coverage pre-checked" below.
2. **assign**: calls `core.assign.assign_one()` directly, the same
   per-file majority-vote pairing `assign-one` exposes standalone, see
   `docs/explanation/assign.md`. Also narrows `{name}_parent_01` down to
   only the parent fids any child was actually assigned to, before clip
   runs.
3. **`_01_clip`**: a thin wrapper joining `parent_fid` onto
   `{name}_child_01` from `{name}_02_assign`, then calling
   `core.edge_clip.main()`, the same per-`parent_fid`-subprocess, adaptively
   grid-tiled clip `edge-clip` exposes standalone, see `docs/explanation/edge_clip.md`.
   When `on_unmatched="passthrough"` (see "Gap-fill passthrough" below),
   this stage also builds `{name}_02_passthrough` (every whole child file
   with no parent overlap at all) and `UNION ALL BY NAME`s it into
   `{name}_03` immediately after the normal clip, before stitch ever runs.
4. **`_02_stitch`**: calls `core.edge_stitch._02_clean.main()` directly, the
   same whole-table `ST_CoverageClean` pass `edge-stitch` exposes standalone,
   see `docs/explanation/edge_stitch.md`. Passthrough rows (if any) are
   already part of `{name}_03` by this point, so they get the same chance
   to resolve seams against their clipped neighbors as everything else.
5. **`_03_outputs`**: the same `check_valid_topology()` hard gate as
   `edge-match`, using its default `gap_maximum_width=SNAP_TOLERANCE` for the same
   parent-layer-hole reason (see `docs/explanation/edge_match.md`'s
   "`check_valid_topology` and parent-layer gaps", `docs/adr/0035`,
   `docs/adr/0039`), an
   issues report listing unassigned children (no dropped-group kind, since
   there are no groups), any passthrough children, plus any leftover gap
   wider than `SNAP_TOLERANCE`, a warning log if any such gap remains, and
   export (only when the issues report has rows).

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

## Gap-fill passthrough

Opt-in via `on_unmatched="passthrough"` (default `"drop"`, unchanged
behavior). A whole child file with no overlap with any parent (a country
genuinely missing from the parent/clip layer) is dropped by default, the
same as always; with passthrough set, that file's own already-extended
geometry is kept in the output unclipped instead, reported as a
`kind='passthrough'` issues row rather than `unassigned`. Scope is
whole-file only: an individual child dropped from an otherwise-matched
file (`core.assign`'s per-file majority vote already decided it doesn't
belong there) is unaffected either way, computed as a set difference of
distinct `source_file` between `{name}_child_01` and its assigned subset,
inside `_01_clip.py` rather than inside `core.assign` itself (see
`docs/adr/0078`). Any `carry_columns` (see `docs/explanation/assign.md`)
are NULL on passthrough rows, filled automatically by the `UNION ALL BY
NAME` that adds them to `{name}_03`, since there's no parent to join
against. `edge-clip` and `edge-match` have no equivalent option: only
`edge-mosaic`'s children are contractually guaranteed to already be a
complete, valid coverage layer, which is what makes an unclipped
passthrough safe here specifically.

## Why neither input is coverage pre-checked

Neither the parent nor the child layer is checked or cleaned for coverage
violations before assign/clip runs (see ADR-0018). `_03_outputs.py`'s hard
`check_valid_topology()` gate on the final stitched output already
guarantees correctness regardless: there is no path where a dirty parent
or child silently reaches export undetected, only a loud failure. The
child layer is additionally assumed to already be a finished `edge_extend()`
output, which `edge-mosaic` never re-verifies.

## edge-match vs. edge-mosaic

| | `edge-match` | `edge-mosaic` |
| --- | --- | --- |
| Input assumption | Child layer is raw, unextended | Child layer is already a finished `edge_extend()` output |
| Assign strategy | `assign-many` (per-child plurality) | `assign-one` (per-file majority vote) |
| Cost driver | Per-group Voronoi extension (~85% of wall time) | Assign + clip + stitch only, no extension |
| Isolation | Two subprocess generations: per-group `edge-extend`, then batched per-`parent_fid` `edge-clip` (`docs/adr/0020`) | Per-`parent_fid` subprocess only, boundary adaptively grid-tiled (`docs/adr/0015`, `docs/adr/0016`, `docs/adr/0017`) |
| When to use | Child layer hasn't been extended yet | Reusing pre-extended layers against a new/different parent |

## Caveats

**Assign runs against overshoot geometry.** See `docs/explanation/assign.md`'s
Caveats section for the full detail on `assign-one`'s per-file majority vote
and its residual risk (a file too small to form a real majority).

**Clip runs one parent fid at a time, each in its own subprocess with its
boundary adaptively grid-tiled.** See `docs/explanation/edge_clip.md` for the
full detail.

**Cross-provenance seam risk.** `docs/explanation/edge_stitch.md` documents
genuine (non-float-noise) seam disagreements up to ~645m between two tiles
computed independently. `edge-mosaic`'s children can come from wholly different
tool versions or vintages (the portolan catalog has per-country pipeline
drift, e.g. `phl` has v01 through v03), with no guarantee that any two
`extended.parquet` files being combined into one `edge_mosaic()` input were even
produced by compatible `edge_extend()` versions (only empirically-confirmed
schema/CRS compatibility). The `check_valid_topology()` hard gate
still runs and raises before export, but a multi-provenance mosaic run
should have its parent-parent boundaries spot-checked visually (e.g. via
the `geo-preview` skill), not just trusted because the hard gate passed.
Use the output's `source_file` column to find which two files actually
meet at a flagged seam.

**Unclipped geometry meeting clipped neighbors.** With
`on_unmatched="passthrough"`, a passthrough file's boundary was never
intersected against the parent layer, unlike every clipped neighbor
around it; any seam disagreement there is on top of the ordinary
cross-provenance risk above, not instead of it. Stitch gets a chance to
resolve it like any other seam, and the hard gate still raises if it
can't, but a passthrough run is worth the same visual spot-check as a
multi-provenance one.
