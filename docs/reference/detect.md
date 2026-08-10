# detect

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `detect` shares with other tools.

## Inputs

- `detect` MUST read the input and reproject it to EPSG:4326 without
  correcting any topology defects first, so the issues stage sees the
  original, unmodified geometry.

## Detecting gaps and overlaps

- `detect` MUST report every fully-enclosed hole in the combined shape of
  all input polygons as a gap, regardless of its size. An open,
  non-enclosed inlet between two polygons MUST NOT be reported as a gap.
- `detect` MUST report every case where two polygons' interiors genuinely
  overlap, or one fully contains the other, as an overlap, regardless of
  its size, whenever the input has any coverage violation at all. If the
  input has no coverage violations, `detect` MUST report zero overlaps
  without running the overlap check. Two polygons that only share a
  boundary edge MUST NOT be reported as an overlap.
- If detecting one kind of defect fails, `detect` MUST still report the
  other kind rather than failing entirely.
- The issues report MUST list, for every defect: a unique key, whether it
  is a gap or an overlap, its area, its width, and its geometry. A gap
  entry MUST also carry a compactness score (how thin and elongated its
  shape is, as opposed to round and plausible); an overlap entry MUST
  also identify the two units involved. Neither MUST appear on the other
  kind's entries.

## Outputs

- `detect` performs no topology hard gate at all; it is a read-only
  inspection, not a fix.
- `detect` MUST always produce an issues report, even when the input had
  zero defects.

## Configuration (`api.detect.detect()` / CLI)

- `detect` MUST process exactly one input file per call.
- The issues-report path MUST default to the input path with an
  `_issues` suffix.
- `detect` MUST raise `FileExistsError` if the output path already
  exists and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `issues`, `outputs`; any
  other value MUST raise `ValueError`.
