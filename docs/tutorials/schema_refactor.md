# schema-refactor

Renames/drops columns per a crosswalk (from `schema-map`, likely
hand-edited afterward).

### Example 1: basic run, output name chosen automatically

    topo-tools schema-refactor example.geojson crosswalk.csv

### Example 2: explicit output

    topo-tools schema-refactor example.gpkg crosswalk.csv example_mapped.gpkg
