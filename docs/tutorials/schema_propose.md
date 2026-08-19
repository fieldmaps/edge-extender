# schema-propose

Proposes a source-column -> target-schema crosswalk for one input file,
deterministically (no LLM). Never renames anything; review/edit the
crosswalk, then run `schema-apply`.

### Example 1: basic run, output name chosen automatically

    topo-tools schema-propose example.geojson target-schema.yaml

### Example 2: explicit output

    topo-tools schema-propose example.gpkg target-schema.yaml crosswalk.json

### Example 3: anchor this file's own admin level

    topo-tools schema-propose admin3.geojson target-schema.yaml --own-level 3

See `docs/examples/target-schemas/cod-ab.yaml` for an example target
schema.
