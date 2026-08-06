"""Non-user-configurable constants for the clean pipeline."""

# Relative headroom added to the widest detected gap's own width when
# --maximum-gap-width=all resolves gap_maximum_width, so the widest gap
# itself reliably clears ST_CoverageClean's <= comparison rather than landing
# exactly on the boundary.
ALL_GAP_WIDTH_EPSILON_FACTOR = 1.001

# Thinness-ratio (Polsby-Popper compactness) cutoff for
# --maximum-gap-width=auto. Not user-configurable.
DEFAULT_THINNESS_RATIO = 0.3

# Escalation ladder for gap_maximum_width when ST_CoverageClean's result
# still has invalid edges (or raises) at the resolved target width --
# confirmed empirically that this is a real, dataset-specific numerical
# instability in GEOS at certain widths, not something snapping_distance
# affects. Each factor multiplies the *original* target (auto/all/explicit),
# so a candidate never sits below what was actually asked for -- only wider,
# never narrower. Sized with real margin above the one confirmed case (a
# ~36m-wide instability that cleared at +1.0%): the last three rungs (5%,
# 10%, 20%) are safety margin beyond anything actually observed. Deliberately
# NOT sized to reach "fill everything" scale -- gap_maximum_width in the
# single-digit-degrees range and up was confirmed to make ST_CoverageClean
# silently erode real polygon area on a real admin-boundary layer (164 fids,
# 190km^2 -> 50km^2 at 10 degrees, fully empty at 20+), not just close gaps.
# There is no safe "big enough to guarantee everything fills" constant; see
# docs/clean.md. If every rung still fails, `_03_clean.py` raises rather
# than silently falling back to a different gap-filling behavior.
GAP_WIDTH_ESCALATION_FACTORS = (1.0, 1.001, 1.002, 1.005, 1.01, 1.02, 1.05, 1.10, 1.20)

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
