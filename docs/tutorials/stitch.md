# stitch

Closes seams in an already-tiled layer with one whole-table coverage-clean
pass.

### Example 1: basic run, output name chosen automatically

    topo-tools stitch tiled.geojson

### Example 2: explicit output

    topo-tools stitch tiled.gpkg stitched.gpkg

### Example 3: custom issues report path

    topo-tools stitch tiled.parquet stitched.parquet --issues-file stitch_report.parquet
