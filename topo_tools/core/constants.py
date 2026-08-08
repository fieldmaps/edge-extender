"""Shared, tool-neutral constants used by more than one pipeline."""

SNAP_TOLERANCE = 0.00000001
# Equal Earth -- used by match/change to rank/compute areas for cross-polygon
# area comparison (never stored).
EQUAL_AREA_CRS = "EPSG:8857"
# Exact (case-sensitive) column names DuckDB's GDAL COPY writer treats
# specially as the feature's implicit FID, colliding with our own internal
# "fid" or a source column already named this way -- confirmed via a minimal
# repro against the installed DuckDB/GDAL: COPY ... (FORMAT GDAL, DRIVER
# 'GPKG') fails outright if the Arrow table has either column literally
# present. core.io.read_and_reproject renames any source column matching
# this set on load, once, so nothing downstream ever has to guard against it
# again.
RESERVED_COLUMN_NAMES = ("fid", "OGC_FID")

# core.clip skips grid-tiling below this vertex count and clips directly.
CLIP_TILE_MIN_VERTICES = 5000
# Target vertices per tile once tiling triggers; cell size is solved from
# this against each parent's own vertex density (see core.clip._adaptive_cell_size).
CLIP_TILE_TARGET_VERTICES = 1350
CLIP_TILE_MIN_CELL = 0.05
CLIP_TILE_MAX_CELL = 5.0

_PARQUET_EXPORT = (
    "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION 'V2')"
)
COPY_OPTS = {
    ".parquet": _PARQUET_EXPORT,
    ".gpkg": "WITH (FORMAT GDAL, DRIVER 'GPKG')",
    ".geojson": "WITH (FORMAT GDAL, DRIVER 'GeoJSON')",
    ".shp": "WITH (FORMAT GDAL, DRIVER 'ESRI Shapefile')",
}
