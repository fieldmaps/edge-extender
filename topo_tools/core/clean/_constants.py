"""Non-user-configurable constants for the clean pipeline."""

# Relative headroom added to the widest qualifying gap's own width for
# --maximum-gap-width=auto, so it reliably clears ST_CoverageClean's <=
# comparison rather than landing exactly on the boundary.
AUTO_GAP_WIDTH_EPSILON_FACTOR = 1.001

# gap_maximum_width for --maximum-gap-width=all: larger than any real
# geographic extent in decimal degrees, so every detected gap qualifies
# without scanning for the widest one. See docs/clean.md.
GAP_MAXIMUM_WIDTH_ALL_DEG = 360.0

# Thinness-ratio (Polsby-Popper compactness) cutoff for
# --maximum-gap-width=auto. Not user-configurable.
DEFAULT_THINNESS_RATIO = 0.3

# Sanity floor on a coverage_clean() attempt's total output area relative to
# the input's, in addition to has_coverage_violations(). Needed because a
# totally empty (or catastrophically eroded) ST_CoverageClean result passes
# has_coverage_violations() as False -- confirmed directly: an empty
# GeometryCollection has no invalid edges to detect, so the "no violations"
# check alone cannot distinguish a successful clean from ST_CoverageClean
# silently destroying the input. Real overlap-resolution shrinkage is a
# small fraction of total area (a few percent at most for realistic data);
# 0.8 is generous headroom above that while reliably catching collapse.
AREA_SANITY_FACTOR = 0.8
