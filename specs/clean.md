# clean

See `specs/README.md` for the MUST/SHOULD/MAY convention.

## Inputs

- `clean` MUST read the input and reproject it to EPSG:4326 without
  correcting any topology defects first, so the issues stage sees the
  original, unmodified geometry.

## Detecting gaps and overlaps

- `clean` MUST report every fully-enclosed hole in the combined shape of
  all input polygons as a gap, regardless of its size or the requested
  gap-fill mode. An open, non-enclosed inlet between two polygons MUST NOT
  be reported as a gap.
- `clean` MUST report every case where two polygons' interiors genuinely
  overlap, or one fully contains the other, as an overlap, regardless of
  its size. Two polygons that only share a boundary edge MUST NOT be
  reported as an overlap.
- If detecting one kind of defect fails, `clean` MUST still report the
  other kind rather than failing entirely.
- The issues report MUST list, for every defect: a unique key, whether it
  is a gap or an overlap, its area, its width, and its geometry. A gap
  entry MUST also carry a compactness score (how thin and elongated its
  shape is, as opposed to round and plausible); an overlap entry MUST
  also identify the two units involved. Neither MUST appear on the other
  kind's entries.

## Fixing gaps and overlaps

- `clean` MUST attempt to fix the input whenever it contains any overlap,
  or any detected gap that qualifies to be filled under the requested
  mode.
- The default gap-fill mode (`auto`) MUST fill a gap only if its
  compactness score marks it as a thin, elongated digitization sliver
  rather than a plausible real feature (e.g. a pond or a strait),
  regardless of the gap's absolute size.
- The `all` mode MUST fill every detected gap, regardless of shape.
- A user-supplied numeric width MUST be honored directly, in decimal
  degrees, with no unit conversion. Requesting any gap-fill mode other
  than `auto`, `all`, or a number MUST raise `ValueError`.
- The default snapping mode (`auto`) MAY use a computed default distance;
  a user-supplied numeric distance, in decimal degrees, MUST be honored
  directly. Requesting any snapping mode other than `auto` or a number
  MUST raise `ValueError`.
- `clean` MUST reject a fix attempt that leaves any defect, turns any
  feature's shape into something other than a valid polygon, loses a large
  share of the input's total area, or loses an unexplained share of a
  single feature's area (a feature with no defect of its own is expected
  to come out essentially unchanged; a feature that was itself part of a
  gap or overlap being resolved may change area substantially, including
  losing all of it, as a legitimate outcome). On rejection, `clean` MUST
  retry with progressively wider values, and MUST NOT ever retry with a
  value narrower than what the requested mode resolved to.
- If `clean` cannot produce a valid fix at any width it attempts, it MUST
  raise `RuntimeError` rather than returning invalid or degraded output.

## Outputs

- `clean` MUST raise `RuntimeError` if the fixed output still contains
  any overlap.
- `clean` MUST NOT raise an error over a gap left unfilled by design. It
  MUST only log a warning naming how many gaps are still unfilled.
- `clean` MUST always produce both the cleaned dataset and the issues
  report, even when the input had zero defects.
- The issues report MUST also state each issue's actual measured outcome,
  not just the defect as originally detected: for an overlap, how much
  each of its two named units' own area actually changed; for a gap, how
  much of the gap's own area ended up covered (zero if left unfilled).
- `clean` MUST report the fixed output's total area change (gained or
  lost) relative to the input.

## Configuration (`api.clean.clean()` / CLI)

- `clean` MUST process exactly one input file per call.
- The cleaned-dataset path MUST default to the input path with a
  `_cleaned` suffix. The issues-report path MUST default to the
  cleaned-dataset path with an `_issues` suffix.
- `clean` MUST raise `FileExistsError` if either output path already
  exists and overwriting wasn't requested.
- If a single pipeline step is requested, it MUST be one of `inputs`,
  `issues`, `clean`, `outputs`. Any other value MUST raise `ValueError`.
