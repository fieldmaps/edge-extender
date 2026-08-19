# schema-apply

Renames/drops columns per a crosswalk (from `schema-propose`, likely
hand-edited afterward).

### Example 1: basic run, output name chosen automatically

    topo-tools schema-apply example.geojson crosswalk.json

### Example 2: explicit output

    topo-tools schema-apply example.gpkg crosswalk.json example_mapped.gpkg
