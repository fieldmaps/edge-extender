# schema-fill

Cascades every admin-hierarchy column down from its nearest non-NULL
shallower level, and stamps a new `adm_lvl` column (overridable via
`--depth-column`) with each row's real depth. Run it against an
already-clipped/stitched layer (an `edge-match`/`edge-mosaic` output),
then `dissolve` normally per level.

### Example 1: basic run, default (generic) schema, output name chosen automatically

    topo-tools schema-fill leaf.parquet

### Example 2: custom target schema

    topo-tools schema-fill leaf.parquet target-schema.yaml

### Example 3: explicit output

    topo-tools schema-fill leaf.gpkg target-schema.yaml filled.gpkg

### Example 4: dissolve every level from a filled table

`adm_lvl` survives each dissolve call automatically (`dissolve`'s existing
auto-keep-constant-column behavior), so a caller can tell a genuine admin2
row from an admin2 group that only ever went as deep as admin1.

    topo-tools schema-fill leaf.parquet filled.parquet
    topo-tools dissolve filled.parquet adm3.parquet --group-by adm3_code,adm2_code,adm1_code
    topo-tools dissolve filled.parquet adm2.parquet --group-by adm2_code,adm1_code
    topo-tools dissolve filled.parquet adm1.parquet --group-by adm1_code

### Example 5: custom depth column name

    topo-tools schema-fill leaf.parquet filled.parquet --depth-column adm_depth

### Example 6: pin the fill to a known reference level

If a country's real depth is known to be admin2, and admin1/admin2 are
already correct source data (any NULL there is genuine, not a fill
artifact), pin the cascade so admin3+ duplicates admin2 verbatim instead
of COALESCE-searching back up to admin1:

    topo-tools schema-fill leaf.parquet filled.parquet --cascade-from-level 2
