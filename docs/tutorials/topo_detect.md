# topo-detect

Scans a single polygon layer for gap/overlap coverage defects and reports
them, without fixing anything.

### Example 1: basic run, output name chosen automatically

    topo-tools topo-detect example.geojson

### Example 2: explicit output

    topo-tools topo-detect example.gpkg example_issues.gpkg
