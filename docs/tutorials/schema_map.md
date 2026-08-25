# schema-map

Maps a source-column -> target-schema crosswalk for one input file,
deterministically (no LLM). Never renames anything; review/edit the
crosswalk, then run `schema-refactor`.

### Example 1: basic run, default (generic) schema, output name chosen automatically

    topo-tools schema-map example.geojson

### Example 2: custom target schema

    topo-tools schema-map example.geojson target-schema.yaml

### Example 3: explicit output

    topo-tools schema-map example.gpkg target-schema.yaml crosswalk.csv

See `topo_tools/core/schema_map/data/default.yaml` for the bundled
default target schema, also usable as a template for your own.
