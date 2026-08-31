# schema-fill

Stamps a new `adm_lvl` column (overridable via `--depth-column`) with each
row's real depth, then cascades every admin-hierarchy column down to that
depth, pinned per row: a genuinely NULL value at a row's own real depth
stays NULL rather than being backfilled from a shallower ancestor. Run it
against an already-clipped/stitched layer (an `edge-match`/`edge-mosaic`
output).

## Example 1: basic run, default (generic) schema, output name chosen automatically

    topo-tools schema-fill admin4.parquet

## Example 2: custom target schema

    topo-tools schema-fill admin4.parquet target-schema.yaml

## Example 3: explicit output

    topo-tools schema-fill admin4.gpkg target-schema.yaml admin4_fill.gpkg

## Example 4: custom depth column name

    topo-tools schema-fill admin4.parquet admin4_fill.parquet --depth-column adm_depth
