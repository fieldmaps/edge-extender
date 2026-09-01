"""Non-user-configurable constants for the extend pipeline."""

from decimal import Decimal

MAX_POINTS = 10_000_000
# Not user-configurable: attempt.py derives effective_distance as
# min(DEFAULT_DISTANCE, natural_res), so this only floors under-detailed files.
DEFAULT_DISTANCE = Decimal("0.0002")
# Caps points per real line segment, bounding the largest exactly-collinear
# point cluster fed to ST_VoronoiDiagram independent of segment length.
MAX_POINTS_PER_SEGMENT = 100
# GEOS closes an unbounded exterior Voronoi cell using its own auto-sized
# envelope, which can exceed valid WGS84 range; clip cells to this instead.
WORLD_BOUNDS_WKT = "POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))"
