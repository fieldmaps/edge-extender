# Run an at-scale test against the portolan catalog

Use the portolan catalog (see `CLAUDE.md`'s Test Datasets section for its
location and the read-only hard rule) when the recommended West Africa
cluster isn't enough, e.g. checking a fix at real multi-thousand-fid
scale, or exercising `change` against a genuine old/new version pair.

## Layout

STAC-like: `{iso3}/{latest,vNN}/{adm0..adm3,lines,points}/{original,
extended,matched}.parquet`. Distinct `vNN` dirs are always genuinely
different content; `latest` is whichever `vNN` is newest.

## Picking a file (`edge-extend` / `edge-match` / `topo-clean`)

Any single `{iso3}/{vNN}/{adm_level}/original.parquet` works. Point every
`--output-path`/`--tmp-dir`/`--debug` export outside the catalog (the
session scratchpad or `/tmp`), never back into `portolan/`.

## Picking a parent/clip layer (`edge-match` / `edge-mosaic`)

Use `/Users/computer/GitHub/fieldmaps/adm0-generator/outputs/adm0/osm/intl/adm0_polygons.parquet`
as the global admin0 parent/clip layer; it's outside the portolan catalog
so it's safe to pass directly as `CLIP_FILE`. Also available at
`https://data.fieldmaps.io/adm0/osm/intl/adm0_polygons.parquet` for anyone
without local repo access.

## Picking an old/new pair (`change`)

1. Browse the country's catalog (local path, or fetch `./{iso3}/catalog.json`
   from the STAC root) and list its `vNN` dirs.
2. Not every country/admin-level has 2+ versions yet, so confirm both `vNN`s
   you want to compare actually exist before running `change`.
3. Run `change` with the older version as the first argument, the newer as
   the second; point every output path outside the catalog.

`docs/explanation/change.md`'s "Portolan-scale profiling" section has real
timing/memory numbers from Philippines admin3 (`v02`->`v03`), Ethiopia
admin3 (`v01`->`v04`), and Ukraine admin3 (`v01`->`v05`) runs, plus a
`--link-by-code` footgun found on the Philippines pair.
`docs/explanation/dissolve.md`'s own "Portolan-scale profiling" section has
a global admin4->admin3 run.

## Prefer the catalog's own GeoParquet over a freshly-converted GDB export

If a global/combined export (e.g. an `.gdb.zip`) exists outside the
catalog for the same content, use the catalog's own per-country/per-level
GeoParquet instead for topology-sensitive testing. An ad hoc
`gdal vector convert` from a zipped FileGDB (OpenFileGDB driver) was found
to introduce real topology defects (`has_invalid_edges()` true) not present
in the canonical portolan GeoParquet of the same 213,503-row dataset,
likely from OGR's `organizePolygons()` part-reassembly heuristic on
many-part multipolygons (see `docs/explanation/dissolve.md`'s profiling
section for the full comparison).
