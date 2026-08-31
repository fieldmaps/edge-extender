# edge-mosaic

Re-clips an already-extended child layer (a prior `edge_extend()` output) into a
new/different parent/clip layer, skipping Voronoi extension entirely.

### Example 1: re-clip a pre-extended layer against a new parent boundary, explicit output

    topo-tools edge-mosaic adm3_extended.parquet adm0_new.geojson adm3_mosaicked.parquet

### Example 2: custom issues report path

    topo-tools edge-mosaic adm3_extended.parquet adm0_new.geojson adm3_mosaicked.parquet \
      --issues-file mosaic_report.parquet

### Example 3: combine multiple pre-extended children files, then re-clip

`--input` MAY be repeated and/or comma-separated.

    topo-tools edge-mosaic afg.parquet world_adm0.geojson out.parquet \
      --input ago.parquet,are.parquet

### Example 4: cascade admin-hierarchy columns and stamp each row's depth before export

    topo-tools edge-mosaic adm3_extended.parquet adm0_new.geojson adm3_mosaicked.parquet --fill-schema
