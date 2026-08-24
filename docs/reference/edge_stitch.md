# edge-stitch

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `edge-stitch` shares with other tools.

## Inputs

- `edge-stitch` MUST read the input and reproject it to EPSG:4326.
- `edge-stitch` MUST NOT coverage-clean the input before stitching: whatever
  seams or defects the input has are exactly what the stitch pass exists
  to close.

## Stitching

- `edge-stitch` MUST run one whole-table `ST_CoverageClean` pass over the
  input, using a fixed snapping-distance-scale gap-closing width, not a
  shape-based heuristic.

## Outputs

- `edge-stitch`'s final output MUST pass the hard gate in
  `docs/reference/shared.md` (no overlap; unlike other tools, an unfilled
  gap does not block export, see `docs/adr/0027`).
- `edge-stitch` MUST export the final cleaned layer.
- `edge-stitch` MUST also export an issues report alongside it, using the
  shared schema in `docs/reference/shared.md`, listing every leftover gap
  wider than `SNAP_TOLERANCE`, so a human can audit what may need review.
  `area_m2`, `max_width_m`, and `thinness_ratio` MUST be populated for
  each row; every other column MUST be null.
- `edge-stitch` MUST produce the issues report only when it has at least one
  row; when it would be empty, no file MUST be written (and a stale file
  from a previous run at that path MUST be removed).

## Configuration (`api.edge_stitch.stitch()` / CLI)

- `edge-stitch`'s input role MAY span multiple already-tiled files, combined
  internally into one table before the clean pass. The CLI additionally
  accepts `--input` (repeatable and comma-separable) alongside the
  glob-capable `INPUT_FILE` positional, matching `edge-mosaic`'s own `--input`
  idiom.
- With a single input file, the output path MUST default to that input
  path with a `_stitched` suffix. With multiple input files, `output_path`
  MUST be given explicitly. The issues-report path MUST default to the
  output path with an `_issues` suffix.
- `edge-stitch` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `topo-clean`, `outputs`; any other
  value MUST raise `ValueError`.
