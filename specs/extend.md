# extend

See `specs/README.md` for the MUST/SHOULD/MAY convention, and
`specs/shared.md` for rules `extend` shares with other tools.

## Inputs

- `extend` MUST read the input and reproject it to EPSG:4326.
- If the reprojected input has any coverage violation (an overlap or a
  mismatched shared edge), `extend` MUST correct it before continuing;
  otherwise it MUST leave the input unmodified.
- Correcting a violation MAY shift any polygon's boundary, not just the
  violating one.
- `extend` MUST NOT distinguish a real hole from a digitization gap --
  both are left for the boundary-extension stage.

## Extracting boundaries

- Each polygon's exterior boundary MUST be its own boundary minus the
  combined boundary of every bounding-box-overlapping neighbor. A polygon
  with no such neighbor MUST keep its full boundary.

## Generating the boundary extension (points and Voronoi cells, retried together)

- `extend` MUST generate points along each polygon's exterior boundary, at
  a target spacing, as input to a Voronoi diagram.
- The target spacing MUST default to the smaller of a fixed default or the
  file's own median real segment length.
- A single real segment MUST NOT contribute more than a fixed cap's worth
  of points.
- Generated points MUST exclude a buffered zone around every shared
  boundary endpoint.
- `extend` MUST build a Voronoi diagram from the points, assign each cell
  to the polygon whose point generated it, and union cells by polygon into
  that polygon's extension.
- On failure, or more points than a fixed maximum, `extend` MUST retry
  with the spacing doubled from the resolved default, up to 10 times, then
  raise.

## Merging

- Each polygon's final geometry MUST be its original geometry combined
  with the portion of its own extension not already covered by a nearby
  original polygon.
- `extend` MUST snap an extension to its nearby original neighbors, using
  a small fixed tolerance, before subtracting them.
- `extend` MUST run one whole-layer coverage-clean pass afterward, using a
  gap-closing width equal to the snapping tolerance, not a shape-based
  heuristic.

## Outputs

- `extend`'s final output MUST pass the hard gate in `specs/shared.md` (no
  overlap, no gap) before export.
- `extend` MUST export the final merged layer.

## Configuration (`api.extend.extend()` / CLI)

- `extend` MUST process exactly one input file per call.
- The output path MUST default to the input path with an `_extended`
  suffix.
- `extend` MUST raise `FileExistsError` if the output exists and
  overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `lines`, `attempt`, `merge`,
  `outputs`; any other value MUST raise `ValueError`.
