# schema-crosswalk

Maps a source-column -> target-schema crosswalk, then immediately
applies it, writing both the crosswalk CSV and the renamed/dropped-column
mapped output in one call (`schema-map` + `schema-refactor` in one step).

### Example 1: basic run, default (COD-AB) schema, output names chosen automatically

    topo-tools schema-crosswalk example.geojson

### Example 2: custom target schema

    topo-tools schema-crosswalk example.geojson target-schema.yaml

### Example 3: explicit outputs

    topo-tools schema-crosswalk example.gpkg target-schema.yaml example_mapped.gpkg example_crosswalk.csv

### Example 4: iterate on a hand-edited crosswalk

    topo-tools schema-crosswalk example.geojson
    # review/edit example_crosswalk.csv, then re-apply without re-mapping:
    topo-tools schema-refactor example.geojson example_crosswalk.csv --overwrite

See `docs/tutorials/schema_map.md`/`docs/tutorials/schema_refactor.md` for the two
underlying tools this composes.
