# extend

Extends polygon boundaries outward using Voronoi diagrams, producing a
complete coverage layer that fills gaps (coastlines, disputed areas, water
bodies).

### Example 1: basic run, output name chosen automatically

    topo-tools extend example.geojson

### Example 2: explicit output

    topo-tools extend example.gpkg example_extended.gpkg

### Example 3: rerun and overwrite a previous output

    topo-tools extend example.parquet example_extended.parquet --overwrite
