"""Non-user-configurable constants for the clean pipeline."""

# Headroom over the widest qualifying gap's width for --maximum-gap-width=auto,
# so it reliably clears ST_CoverageClean's <= comparison.
AUTO_GAP_WIDTH_EPSILON_FACTOR = 1.01

# gap_maximum_width for --maximum-gap-width=all: larger than any real
# geographic extent, so every detected gap qualifies without scanning.
GAP_MAXIMUM_WIDTH_ALL_DEG = 360.0

# Thinness-ratio (Polsby-Popper compactness) cutoff for --maximum-gap-width=auto.
DEFAULT_THINNESS_RATIO = 0.3

# Baseline area-loss tolerance with no detected overlaps to explain any loss --
# double the ~1% per-fid renoding drift confirmed on real defect-dense data.
AREA_NOISE_FACTOR = 0.02

# Multiplier on detected overlap area for how far ST_CoverageClean may
# legitimately redraw beyond the overlap's own footprint while resolving it.
OVERLAP_LOSS_HEADROOM = 3.0
