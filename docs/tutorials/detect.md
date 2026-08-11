# detect

Scans a single polygon layer for gap/overlap coverage defects and reports
them, without fixing anything.

### Example 1: basic run, output name chosen automatically

    topo-tools detect example.geojson

### Example 2: explicit output

    topo-tools detect example.gpkg example_issues.gpkg
