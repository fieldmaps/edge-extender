# match

Fits a finer child polygon layer into a coarser parent/clip layer, extending
and clipping each child to its own parent group.

### Example 1: fit an admin4 layer into a single country boundary, output name chosen automatically

    topo-tools match adm4.geojson adm0.geojson

### Example 2: fit admin3 into admin2 groups, explicit output

    topo-tools match adm3.gpkg adm2.gpkg adm3_matched.gpkg

### Example 3: custom issues report path

    topo-tools match adm3.gpkg adm2.gpkg adm3_matched.gpkg \
      --issues-file match_report.gpkg
