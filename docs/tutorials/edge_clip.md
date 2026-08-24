# edge-clip

Assigns each child to its parent, then clips it to that parent's geometry.

### Example 1: clip a children layer against a parent/clip layer, explicit output

    topo-tools edge-clip children.parquet adm1.geojson clipped.parquet

### Example 2: custom issues report path

    topo-tools edge-clip children.parquet adm1.geojson clipped.parquet \
      --issues-file clip_report.parquet

### Example 3: clip multiple children files against one shared parent load

`--input`/`--output` MAY each be repeated and/or comma-separated; `--name`
is required in this form.

    topo-tools edge-clip afg.parquet world_adm0.geojson afg_out.parquet \
      --input ago.parquet,are.parquet --output ago_out.parquet,are_out.parquet \
      --name portolan_batch
