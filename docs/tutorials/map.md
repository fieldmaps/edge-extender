# map

Maps a source-column -> target-schema crosswalk for one input file,
deterministically (no LLM). Never renames anything; review/edit the
crosswalk, then run `refactor`.

### Example 1: basic run, default (COD-AB) schema, output name chosen automatically

    topo-tools map example.geojson

### Example 2: custom target schema

    topo-tools map example.geojson target-schema.yaml

### Example 3: explicit output

    topo-tools map example.gpkg target-schema.yaml crosswalk.csv

See `topo_tools/core/map/data/cod-ab.yaml` for the bundled
default target schema, also usable as a template for your own.
