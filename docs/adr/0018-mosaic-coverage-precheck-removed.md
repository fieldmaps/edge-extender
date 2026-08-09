# 0018: Drop mosaic's parent and child coverage pre-checks entirely

## Status

Accepted.

## Context

`mosaic`'s `_02_assign.py` ran `has_coverage_violations`/`coverage_clean` on
the input parent before assigning children to it; `_01_inputs.py` ran the
same check on each child via `extend`'s own loader. Both were redundant with
`_05_outputs.py`'s hard `check_overlaps`/`check_gaps` gate on the final
merged output, which already raises `RuntimeError` on any violation — there
is no code path where a dirty parent or child silently produces a bad
export.

The parent-side check was also the actual blocker on real data: a
`ST_CoverageInvalidEdges_Agg` pass over Canada+USA admin0 (two of the
largest, most complex single polygons in the catalog) ran past 66 minutes
without finishing. Root-caused to individual-polygon vertex complexity, not
row count or aggregate vertex count: Indonesia admin3 (80K+ rows, 15M+ total
vertices) checked in ~2s, while a single Canada-scale polygon alone was
enough to make the check pathological. Admin0 (country) records concentrate
all national boundary complexity into one polygon; admin1+ subdivision
structurally splits that same complexity across many smaller polygons,
capping any single row's vertex count. A full 372-file scan of the portolan
catalog's `extended.parquet` files (all countries, admin 0-4) found a worst
single-row case of 138,143 vertices (Thailand admin1, 0.60s) and a worst
aggregate case of 15.6M vertices across 7,425 rows (Thailand admin3, 4.97s)
— and zero coverage violations anywhere in the catalog.

## Decision

Both pre-checks are removed outright, not made conditional: `_02_assign.py`
no longer imports or calls `has_coverage_violations`/`coverage_clean` on the
parent, and `_01_inputs.py` loads both child and parent raw via
`core.io.read_and_reproject`, the same shared leaf `clean` uses, instead of
delegating to `extend`'s loader. The `skip_parent_clean` flag built to make
the parent check optional was itself removed once the check it gated was
gone. `_05_outputs.py`'s hard gate is now the pipeline's sole correctness
guarantee, for both roles.

## Consequences

A Chile admin3 mosaic run that had been stuck past 47 minutes on the parent
pre-check completed in ~14m9s once it was skipped, producing 345 output rows
with 0 issues. The West Africa regression (653 rows, 0 issues) matched its
pre-existing baseline exactly. `mosaic` no longer imports anything from
`core.match` or `core.extend`; `_02_assign.py` only needs `core.clip`'s
`subdivide_boundary` (for its own oversized-parent-part tiling, described in
`docs/explanation/mosaic.md`) alongside the other neutral leaf modules.
