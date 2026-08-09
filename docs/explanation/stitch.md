# Stitch Explanation

`stitch` closes seams in an already-tiled polygon layer with one
whole-table `ST_CoverageClean` pass: the operation `match` and `mosaic`
each ran internally as their own final merge stage before this extraction.
It is the fixed point both tools converge on regardless of how their tiles
were produced (per-group Voronoi extension for `match`, per-parent clip for
`mosaic`): once a layer's independently-computed tiles sit next to each
other, whatever seam disagreements remain between them get closed here.

## Usage

```sh
topo-tools stitch tiled.geojson
```

```python
from topo_tools import stitch

stitch("tiled.parquet", "stitched.parquet")
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_stitched` suffix.

Run `topo-tools stitch --help` for the full, always-current option list.

## Pipeline

1. **`_01_inputs`**: loads and reprojects the input via
   `core.io.read_and_reproject`, without coverage-cleaning it first (see
   below).
2. **`_02_clean`**: one whole-table `ST_CoverageClean` pass
   (`fids=None`, `gap_maximum_width=SNAP_TOLERANCE`).
3. **`_03_outputs`**: the same `check_overlaps`/`check_gaps` hard gate
   every tool's final output goes through, then export.

## Why whole-table, never scoped to a fid subset

`coverage_clean()` (`core/coverage.py`) technically accepts a `fids` list
to scope the clean pass to a subset of rows, but `stitch` always calls it
with `fids=None`. Per-fid violator scoping was deliberately removed from
`extend`'s own merge stage once already because it reintroduced seam-gap
bugs (see `docs/explanation/topology.md`). By construction, every point of
a tiled layer's extent belongs to exactly one surviving fid, so anything
`ST_CoverageClean` finds to close is seam noise at tile-to-tile
boundaries, not a real feature to protect.

## Seam gaps are real geometry disagreements, not float noise

Seam gaps between two independently-computed tiles (two Voronoi
extensions, or two clipped parent regions) can run from slivers up to
hundreds of meters, confirmed on Burundi's admin2-into-admin1 case,
where 171 invalid cross-group edges ranged up to 0.0058 degrees (~645 m),
averaging ~12 m, against a `SNAP_TOLERANCE` of `1e-8` degrees (~1.1 mm). No
vertex-snapping tolerance in a sane range closes a gap that size; it is
genuine gap-filling work between two pieces computed with no knowledge of
each other, which is exactly what `stitch`'s whole-table pass is for.
Pre-snapping either side of the tiling step's own intersection (tried and
reverted twice, see `docs/explanation/match.md`) made no measurable
difference, confirming the gap is a real geometric disagreement between
tiles, not float noise from a shared vertex computed twice by two
independent calls.

## No coverage pre-check, no issues report

`_01_inputs.py` does not coverage-clean the input, consistent with `clip`
and `assign`; these are all purely mechanical primitives; the final hard
gate in `_03_outputs.py` is the correctness guarantee, not an opinion any
one stage holds about its input's cleanliness. `stitch` also has no issues
report: unlike `match`/`mosaic`/`clean`, it has no concept of a "dropped"
row: every input row survives into the cleaned output.
