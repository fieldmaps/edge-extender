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
   When `merge` is set (see "Parent gap-fill and child passthrough" below),
   this stage also `UNION ALL BY NAME`s every whole unmatched child file's
   own already-extended geometry into `{name}_03` immediately after the
   normal clip; the api layer then calls the shared
   `core.assign.fill_unmatched_parents()` to append every zero-children
   parent's own geometry into the same table, before stitch ever runs.
4. **`_02_stitch`**: calls `core.edge_stitch._02_clean.main()` directly, the
   same whole-table `ST_CoverageClean` pass `edge-stitch` exposes standalone,
   see `docs/explanation/edge_stitch.md`. Passthrough/gap-fill rows (if any)
   are already part of `{name}_03` by this point, so they get the same
   chance to resolve seams against their clipped neighbors as everything else.
5. **`_03_outputs`**: the same `check_valid_topology()` hard gate as
   `edge-match`, using its default `gap_maximum_width=SNAP_TOLERANCE` for the same
   parent-layer-hole reason (see `docs/explanation/edge_match.md`'s
   "`check_valid_topology` and parent-layer gaps", `docs/adr/0035`,
   `docs/adr/0039`), an
   issues report listing unassigned/passthrough children (no dropped-group
   kind, since there are no groups), any gap-filled parents, plus any
   leftover gap wider than `SNAP_TOLERANCE`, a warning log if any such gap
   remains, and export (only when the issues report has rows).

## Multi-file children

Unlike every other tool here, the child role MAY span multiple files in one
call (the portolan catalog stores one `extended.parquet` per country, never
pre-combined); the parent/clip layer stays single-file. `output_path` MUST
be given explicitly whenever multiple paths are passed, since there's no
single filename to default one from, and `step` MUST be `None` (see
`docs/adr/0079`).

With more than one input path, `_mosaic_multi_file()` (`api/edge_mosaic.py`)
runs `inputs`+`assign`+`clip` in a per-file loop instead of combining every
file into one table up front, the same memory-safe pattern standalone
`edge-clip`'s own multi-file mode used before it was reverted to a strict
1:1 primitive (ADR-0023, ADR-0024, ADR-0080): the parent is loaded once
into a pristine snapshot and its heavy-part tile decomposition cached
(`core.assign.prepare_parent_tiles()`), then each children file is loaded,
assigned, and clipped alone against a fresh copy of that snapshot, one at a
time. Each file's clip result is folded into a running `{name}_03}`
accumulator immediately (`UNION ALL BY NAME`) rather than held until a
final combine, keeping peak memory to roughly one parent plus one children
file at a time, not one parent plus every children file. `fid` is kept
globally unique across the whole run via a running offset applied right
after each file loads (not by the union-time `row_number()` a
single-file/combined-table run uses), then reassigned fresh via
`ROW_NUMBER()` over the fully accumulated result once the loop ends,
preserving the same "fid is renumbered fresh after the union" contract a
combined-table run also guarantees. `stitch`/`outputs` still run exactly
once, over the fully accumulated result, since closing a seam between two
files' clipped output needs both sides' geometry at once (see ADR-0079).
Every row on the internal `{name}_04` table still carries a `source_file`
column tagging its origin file, whichever assembly path produced it; it's
an `assign-one` working column, stripped before the exported output (see
`docs/adr/0087`).

## Parent gap-fill and child passthrough

Both opt-in via the single boolean `merge` flag (CLI: `--merge`), off by
default; `--parent-include`/`--parent-exclude`/`--child-include`/
`--child-exclude`/`--prefer` further narrow which columns survive (see
`docs/explanation/assign.md`).

**Child passthrough.** A whole child file with no overlap with any parent
(a country genuinely missing from the parent/clip layer) is dropped by
default; with `merge` set, that file's own already-extended geometry is
kept in the output unclipped instead, reported as a `kind='passthrough'`
issues row rather than `unassigned`. Scope is whole-file only: an
individual child dropped from an otherwise-matched file (`core.assign`'s
per-file majority vote already decided it doesn't belong there) is
unaffected either way. `_01_clip.py`'s `main()` builds this directly as a
`UNION ALL BY NAME` selecting every child row whose fid is in
`{name}_02_unassigned`, immediately after the normal clip.

**Parent gap-fill.** A parent matched by zero children is dropped by
default; with `merge` set, that parent's own geometry and carried columns
are kept in the output unclipped instead, reported as a `kind='gap-fill'`
row. This is the shared `core.assign.fill_unmatched_parents()` helper
(relocated from a mosaic-local `fill_gaps()` this session so `edge-match`
can call it too, see `docs/adr/0088`), called from the api layer right
after `_01_clip.main()` returns, against a `{name}_parent_full` snapshot
taken before assign narrows `{name}_parent_01` to only-matched fids.

Both mechanisms are identical in outcome to `edge-match`'s own `merge`,
given an equivalent already-extended/raw child set against the same
parent (see `docs/explanation/edge_match.md`). `edge-clip` has no
equivalent option (it stays a strict 1:1 primitive with no drop/keep
decision to make). `merge` always couples attribute carry-forward with
both passthrough mechanisms; there is no way to get one without the
other (see `docs/adr/0079`, `docs/adr/0088`).

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
Use `--debug` to inspect the `{name}_04` table's `source_file` column
(dropped from the exported output, see `docs/adr/0087`) to find which two
files actually meet at a flagged seam.

**Unclipped geometry meeting clipped neighbors.** With `--merge` set, a
passthrough file's boundary was never intersected against the parent layer,
unlike every clipped neighbor
around it; any seam disagreement there is on top of the ordinary
cross-provenance risk above, not instead of it. Stitch gets a chance to
resolve it like any other seam, and the hard gate still raises if it
can't, but a passthrough run is worth the same visual spot-check as a
multi-provenance one.

## Opt-in `schema-fill` composition (`fill_schema`)

`edge-mosaic` MAY invoke `schema-fill`'s own fill logic itself, right
after stitching and before export, via `fill_schema=True` (CLI:
`--fill-schema`). This lives entirely in `api/edge_mosaic.py`, at both
insertion points (the single-file step loop's `outputs` branch and
`_mosaic_multi_file()`'s own final stage), calling
`core.schema_fill._02_fill.main()` directly through the private
`api._schema_fill_compose` helper; `core.edge_mosaic` itself is
unchanged and still MUST NOT depend on `core.schema_fill`/
`core.schema_map` (see `docs/reference/shared.md`, `docs/adr/0095`).

`fill_schema` and `merge` are conceptually complementary but
independently gated flags, not aliases: `merge`'s own
`fill_unmatched_parents()` (`docs/adr/0083`) fills a *geometry-coverage*
gap, a parent with zero matched children, by keeping its own unclipped
geometry in the output; `fill_schema` fills a *schema-depth* gap, a row
whose admin-hierarchy columns don't reach as deep as some other row's,
by cascading each column family down to the row's own real depth. Both
can be set together freely; neither implies the other.
