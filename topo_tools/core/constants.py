"""Shared, tool-neutral constants used by more than one pipeline."""

import re

SNAP_TOLERANCE = 0.00000001
# core.coverage.coverage_clean_escalating adds this to snapping_distance
# per retry when ST_CoverageInvalidEdges_Agg still flags the output.
SNAP_ESCALATION_STEP = SNAP_TOLERANCE
# Caps the retry loop at SNAP_TOLERANCE + this many extra steps (9 ->
# 1e-7 deg, ~1.1cm).
SNAP_ESCALATION_MAX_STEPS = 9
# Equal Earth, used by match/change to rank/compute areas for cross-polygon
# area comparison (never stored).
EQUAL_AREA_CRS = "EPSG:8857"
# Column names DuckDB's GDAL COPY writer treats specially as the feature's
# implicit FID; COPY (FORMAT GDAL) fails outright if either is present.
RESERVED_COLUMN_NAMES = ("fid", "OGC_FID")

# GIS bookkeeping columns map/refactor exclude as noise, not "real" source
# data: case-insensitive exact match, not a heuristic.
NOISE_COLUMNS = frozenset(
    {
        "objectid",
        "globalid",
        "fid",
        "shape_leng",
        "shape_length",
        "shape__length",
        "shape_area",
        "shape__area",
        # GDAL's own synthesized feature index, see RESERVED_COLUMN_NAMES.
        "ogc_fid",
        "ogc_fid_orig",
        "fid_orig",
    }
)

_NOISE_SUFFIX_RE = re.compile(r"_(\d+)$")
# ESRI Shapefile's DBF driver caps field names at this many characters total,
# truncating the base name to make room for a disambiguating "_N" suffix.
_DBF_FIELD_NAME_LIMIT = 10


def is_noise_column(name: str) -> bool:
    """Check name, or its GDAL collision-suffixed/DBF-truncated form, is noise."""
    lowered = name.lower()
    if lowered in NOISE_COLUMNS:
        return True
    match = _NOISE_SUFFIX_RE.search(lowered)
    if not match:
        return False
    base = lowered[: match.start()]
    if base in NOISE_COLUMNS:
        return True
    return len(lowered) == _DBF_FIELD_NAME_LIMIT and any(
        noise.startswith(base) for noise in NOISE_COLUMNS
    )


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
