# stitch

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `stitch` shares with other tools.

## Inputs

- `stitch` MUST read the input and reproject it to EPSG:4326.
- `stitch` MUST NOT coverage-clean the input before stitching -- whatever
  seams or defects the input has are exactly what the stitch pass exists
  to close.

## Stitching

- `stitch` MUST run one whole-table `ST_CoverageClean` pass over the
  input, using a fixed snapping-distance-scale gap-closing width, not a
  shape-based heuristic.

## Outputs

- `stitch`'s final output MUST pass the hard gate in
  `docs/reference/shared.md` (no overlap, no gap) before export.
- `stitch` MUST export the final cleaned layer.

## Configuration (`api.stitch.stitch()` / CLI)

- `stitch` MUST process exactly one input file per call.
- The output path MUST default to the input path with a `_stitched`
  suffix.
- `stitch` MUST raise `FileExistsError` if the output exists and
  overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `clean`, `outputs`; any other
  value MUST raise `ValueError`.
