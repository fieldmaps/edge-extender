# change

Compares two versions of a polygon layer and classifies every unit as
unchanged, renamed, modified, relocated, split, merge, complex, created, or
removed.

### Example 1: compare two versions by spatial overlap alone, output name chosen automatically

    topo-tools change admin2_2020.geojson admin2_2024.geojson

### Example 2: explicit output and overlay file paths

    topo-tools change old.gpkg new.gpkg changelog.csv --overlay-file overlay.gpkg

### Example 3: also link units sharing a unique code across versions

    topo-tools change old.gpkg new.gpkg --link-by-code \
      --code-column-a adm2_pcode --code-column-b adm2_pcode

### Example 4: loosen the "related" threshold for heavily redrawn boundaries

    topo-tools change old.parquet new.parquet --tau-match 0.6
