# TODO

## Memory, from overnight stress testing (2026-08-26)

- World-scale verification (fieldmaps global adm0 as parent) hits an 8GB
  swap safety cap on a 16GB machine before completing, for `edge-mosaic`
  and `edge-match` alike, regardless of `--merge`/`--prefer`. Rerun on a
  machine with more headroom, or scope the parent to a regional subset,
  to actually validate the cross-tool identical-results guarantee at
  world scale.
