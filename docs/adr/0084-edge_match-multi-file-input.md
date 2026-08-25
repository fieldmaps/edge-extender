# 0084: `edge-match` accepts multiple children files per call

## Status

Accepted.

## Context

`edge-mosaic` already combines several already-extended children files
against one shared parent in a single call, via a memory-bounded per-file
loop (ADR-0079). `edge-match` had no equivalent: it only accepted one raw
(unextended) children file per call. A caller wanting several countries'
raw admin boundaries matched and extended together against one shared
parent had to run `edge-match` once per country, which loses the benefit
of `edge-match`'s own per-`parent_fid` Voronoi extension (`_02_groups.py`)
merging children from different files that land on the same parent into
one shared group; N independent single-file runs extend each country in
isolation instead, with weaker shared-border behavior at the seam.

`edge-match`'s pipeline has an extra stage `edge-mosaic` does not: groups
(per-`parent_fid` Voronoi extension) runs between assign and clip.
Grouping is keyed purely by `parent_fid` (`_02_groups.py::list_groups`),
with no `source_file` awareness, so children from different files sharing
a `parent_fid` already combine into one group automatically, as long as
groups runs once against the fully accumulated `_02_assign`, not per file.
This differs from `edge-mosaic`, where clip is itself embarrassingly
per-file and folds directly into the loop.

## Decision

1. **Per-file loop scoped to inputs and assign only**, mirroring
   `edge-mosaic`'s `_mosaic_multi_file()` shape (ADR-0079) but stopping one
   stage earlier. A new private `_match_multi_file()` (`api/edge_match.py`)
   loads the parent once into a `{name}_parent_full` snapshot, calls
   `core.assign.prepare_parent_tiles()` once, then for each children file:
   restores `{name}_parent_01` from the snapshot, loads and coverage-cleans
   just that file's children, applies a running `fid_offset`, runs
   `assign_one(use_cached_tiles=True)`, and folds `{name}_child_01`,
   `{name}_02_assign`, and `{name}_02_unassigned` into accumulators. Groups,
   clip, stitch, and outputs then run exactly once, after the loop, over
   the fully accumulated result, so cross-file children sharing a
   `parent_fid` extend together.
2. **`{name}_parent_01` is restored from the full snapshot once more after
   the loop**, before groups/clip run: `assign_one` narrows
   `{name}_parent_01` to only that iteration's matched fids, so after the
   last file the table would otherwise hold only the last file's matches,
   not the union needed by clip.
3. **`--multi-parent`/`multi_parent` is rejected outright when more than
   one children file is given** (`ValueError`), since `assign_many`'s
   per-child plurality logic has no cross-file semantics defined and was
   not designed for this case.
4. **`step` and a missing `output_path` are rejected the same way
   `edge-mosaic` already rejects them** for its own multi-file calls
   (ADR-0079): the per-file loop has no clean external resumption point,
   and there is no single input file to derive a default output path from.
5. **`source_file` is un-nulled in issue rows.** Multi-file input makes
   per-row file provenance meaningful for the first time. `_02_unassigned`
   (both `assign_one` and, newly, `assign_many`) and `{name}_03b`
   (`_record_dropped_group`, newly) already source directly from
   `{name}_child_01`, so adding `source_file` to their SELECT lists is a
   direct passthrough, no join required; `{name}_04_dropped` (clip-empty)
   already carries it through the extend pipeline's `SELECT o.* EXCLUDE
   (geom), ...` reattachment (`core/edge_extend/_05_merge.py`). Only the
   shared `gap` issue kind stays NULL, since a coverage gap has no single
   originating file.
6. **`_fold()` is duplicated, not shared with `edge-mosaic`'s copy.** The
   two loops' per-iteration bodies diverge (mosaic also folds a per-file
   clip result; match does not clip per-file), so a shared helper would
   need a callback parameter for little benefit; duplicating the ~10-line
   helper is the pragmatic choice.

## Consequences

`edge-match` gains the same `--input`/glob CLI surface `edge-mosaic`
already has, and combines raw children files with the same peak-RSS
profile as `edge-mosaic`'s own multi-file mode (roughly parent plus one
children file in memory at a time, not parent plus every children file).
`step` and default-output-path behavior become unavailable for multi-file
calls, matching `edge-mosaic`'s existing precedent, not a new restriction
pattern. `--multi-parent` remains fully available for single-file calls.
No change to `_02_groups.py`'s grouping logic, `_03_clip.py`, or
`_04_stitch.py`: they already operate correctly on however many rows land
in the fully accumulated tables, regardless of file count.
