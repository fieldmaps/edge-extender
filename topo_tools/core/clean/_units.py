"""Degrees -> meters conversion for issues-file reporting columns only.

All data is normalized to EPSG:4326 (degrees) by inputs.py, so
ST_CoverageClean and ST_CoverageInvalidEdges_Agg's distance parameters
(`--snapping-distance`/`--maximum-gap-width`) are taken directly in decimal
degrees -- no conversion, matching GDAL/OGR's convention that a distance
parameter on an unprojected layer is in the layer's native units. This
module only converts the *other* direction, degrees/square-degrees to
meters/square-meters, so the issues file's `area_m2`/`max_width_m` columns
are human-readable; it scales by the dataset's centroid latitude (one
degree of longitude shrinks by cos(latitude)), approximate over very large
north-south extents but adequate for reporting. Ported from
topo-tools-js/src/lib/tools/topology-cleaner/pipeline/units.ts.
"""

from math import cos, radians

METERS_PER_DEGREE = 111_320


def cos_lat_factor(centroid_lat: float) -> float:
    """Latitude-scale factor, guarded near the poles so it never collapses to ~0."""
    return max(cos(radians(centroid_lat)), 0.05)


def m2_to_deg_sq(area_m2: float, centroid_lat: float) -> float:
    """Convert an area in square meters to square degrees at the given latitude."""
    return area_m2 / (METERS_PER_DEGREE**2 * cos_lat_factor(centroid_lat))
