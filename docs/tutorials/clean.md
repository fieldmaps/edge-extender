# clean

Detects and fixes gap/overlap coverage defects in a single polygon layer,
reporting the fix outcome for manual review.

### Example 1: explicit output (default is INPUT_FILE with a "_cleaned" suffix)

    topo-tools clean example.geojson example_cleaned.geojson

### Example 2: fill thin/sliver-shaped gaps regardless of width

    topo-tools clean example.gpkg --maximum-gap-width thin

### Example 3: fill every detected gap, not just slivers

    topo-tools clean example.gpkg --maximum-gap-width all

### Example 4: custom issues report path and snapping distance

    topo-tools clean example.parquet --issues-file example_report.parquet \
      --snapping-distance 0.0001
