"""Non-user-configurable constants for the extend pipeline."""

from decimal import Decimal

MAX_POINTS = 10_000_000
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
# tested values, with zero downside on files that don't hit the cap.
MAX_POINTS_PER_SEGMENT = 100
