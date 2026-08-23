# crosswalk

Maps a source-column -> target-schema crosswalk, then immediately
applies it, writing both the crosswalk CSV and the renamed/dropped-column
mapped output in one call (`map` + `refactor` in one step).

### Example 1: basic run, default (COD-AB) schema, output names chosen automatically

    topo-tools crosswalk example.geojson

### Example 2: custom target schema

    topo-tools crosswalk example.geojson target-schema.yaml

### Example 3: explicit outputs

    topo-tools crosswalk example.gpkg target-schema.yaml example_mapped.gpkg example_crosswalk.csv

### Example 4: iterate on a hand-edited crosswalk

    topo-tools crosswalk example.geojson
    # review/edit example_crosswalk.csv, then re-apply without re-mapping:
    topo-tools refactor example.geojson example_crosswalk.csv --overwrite

See `docs/tutorials/map.md`/`docs/tutorials/refactor.md` for the two
underlying tools this composes.
