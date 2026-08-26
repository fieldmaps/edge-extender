# TODO

## Memory, from overnight stress testing (2026-08-26)

- World-scale verification (fieldmaps global adm0 as parent) hits an 8GB
  swap safety cap on a 16GB machine before completing, for `edge-mosaic`
  and `edge-match` alike, regardless of `--merge`/`--prefer`. Rerun on a
  machine with more headroom, or scope the parent to a regional subset,
  to actually validate the cross-tool identical-results guarantee at
  world scale.
- `idn`/`phl` admin4 raw children OOM `edge-match`'s Voronoi extension
  step: `idn` hits DuckDB's default 12.7GB memory ceiling directly;
  `phl` hits the Voronoi resampling vertex-count guard, falls through
  retries, and ends in `INVALID_EDGES`. `edge-mosaic` on the same files
  succeeds (skips extension). Extend `docs/explanation/voronoi-memory.md`
  with these two admin4 floors once measured on a bigger box, alongside
  the existing admin3 entries.
- No runtime memory gate exists anywhere in the pipeline (deliberate,
  per `docs/adr/0013`); confirm that stance still holds now that admin4
  scale has been observed hitting DuckDB's full default budget, not
  just the smaller documented admin3 floors.
