# TODO

## Memory, from overnight stress testing (2026-08-26)

- World-scale `--merge` verification against the real fieldmaps global adm0
  (~730MB, 315 parts) hits an 8GB swap safety cap on this 16GB machine
  before completing, for `edge-mosaic` and `edge-match` alike, regardless of
  `--merge`/`--prefer`. Root cause: `fill_unmatched_parents()` always reads
  the full untouched parent snapshot for gap-fill, independent of children's
  bbox (`docs/adr/0085` only bbox-prefilters *tiling*, not gap-fill). This
  machine has no more RAM to add, so the fix is scoping the parent, not
  the machine: against a regional 8-country subset (West Africa cluster)
  instead of the full global file, `edge-mosaic --merge` (both narrow
  `--parent-include` and `--prefer parent`) completes in ~15s with no swap
  pressure and produces consistent 139-row output either way.

- A genuine global adm4 build (every portolan country's adm4 fit against
  the global adm0 parent) still inherits the first finding above: skip
  `--merge` if every admin0 unit is expected to end up with matching adm4
  children, avoiding the full-parent-snapshot gap-fill cost entirely.
