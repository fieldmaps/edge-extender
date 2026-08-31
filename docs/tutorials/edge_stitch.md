# edge-stitch

Closes seams in an already-tiled layer with one whole-table coverage-clean
pass.

### Example 1: basic run, output name chosen automatically

    topo-tools edge-stitch tiled.geojson

### Example 2: explicit output

    topo-tools edge-stitch tiled.gpkg stitched.gpkg

### Example 3: custom issues report path

    topo-tools edge-stitch tiled.parquet stitched.parquet --issues-file stitch_report.parquet

### Example 4: combine every already-clipped file into one global output

    topo-tools edge-stitch "tmp/clipped/*.parquet" stitched.parquet

### Example 5: cascade admin-hierarchy columns and stamp each row's depth before export

    topo-tools edge-stitch tiled.parquet stitched.parquet --fill-schema
