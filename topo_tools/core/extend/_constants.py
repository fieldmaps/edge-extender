"""Non-user-configurable constants for the extend pipeline."""

from decimal import Decimal

MAX_POINTS = 10_000_000
SNAP_TOLERANCE = 0.00000001
# Equal Earth -- used by match/change to rank/compute areas for cross-polygon
# area comparison (never stored). Lives here, not in either tool's own
# _constants.py, so both import the same literal instead of each declaring
# their own copy of it -- match and change still don't depend on each other,
# only on this shared hub, same as SNAP_TOLERANCE above.
EQUAL_AREA_CRS = "EPSG:8857"
# Exact (case-sensitive) column names DuckDB's GDAL COPY writer treats
# specially as the feature's implicit FID, colliding with our own internal
# "fid" or a source column already named this way -- confirmed via a minimal
# repro against the installed DuckDB/GDAL: COPY ... (FORMAT GDAL, DRIVER
# 'GPKG') fails outright if the Arrow table has either column literally
# present. inputs.main renames any source column matching this set on load,
# once, so nothing downstream (including match's export) ever has to guard
# against it again.
RESERVED_COLUMN_NAMES = ("fid", "OGC_FID")
# Not user-configurable: attempt.py derives a per-file effective_distance as
# min(DEFAULT_DISTANCE, natural_res), so this only serves as (a) the floor
# for boundaries with no fine natural detail — natural_res always wins when
# finer, so this can never coarsen an already-detailed file — and (b) the
# fallback when a file has no real segments at all. A CLI/env override was
# removed: the only documented use case for a larger value ("the entire
# world") didn't actually work, since natural_res already wins over any
# coarser override wherever real detail exists.
DEFAULT_DISTANCE = Decimal("0.0002")
# Cap on points generated per real (untouched) line segment; bounds the size
# of the largest exactly-collinear point cluster fed to ST_VoronoiDiagram,
# independent of that segment's raw length. 100 was the smallest of several
# tested values, with zero downside on files that don't hit the cap. See
# docs/voronoi-memory.md for the full timing comparison and rationale.
MAX_POINTS_PER_SEGMENT = 100

_PARQUET_EXPORT = (
    "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION 'V2')"
)
COPY_OPTS = {
    ".parquet": _PARQUET_EXPORT,
    ".gpkg": "WITH (FORMAT GDAL, DRIVER 'GPKG')",
    ".geojson": "WITH (FORMAT GDAL, DRIVER 'GeoJSON')",
    ".shp": "WITH (FORMAT GDAL, DRIVER 'ESRI Shapefile')",
}
