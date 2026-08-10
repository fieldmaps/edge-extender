"""Unit tests for core/coverage.py's width-aware gap checking."""

import duckdb
import pytest

from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import check_valid_topology, count_gaps, has_gaps


def _write_polygon_with_hole(conn, hole_width):
    """One polygon: a 3x3 square with a centered hole_width square hole cut out."""
    w = hole_width
    lo, hi = 1.5 - w / 2, 1.5 + w / 2
    wkt = (
        f"POLYGON((0 0, 3 0, 3 3, 0 3, 0 0), "
        f"({lo} {lo}, {hi} {lo}, {hi} {hi}, {lo} {hi}, {lo} {lo}))"
    )
    conn.execute(
        "CREATE OR REPLACE TABLE synth AS "
        f"SELECT 1 AS fid, ST_GeomFromText('{wkt}') AS geom"
    )


def test_has_gaps_tolerates_wide_hole_when_scoped():
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        _write_polygon_with_hole(conn, hole_width=2.0)
        assert has_gaps(conn, "synth", gap_maximum_width=0)
        assert not has_gaps(conn, "synth", gap_maximum_width=SNAP_TOLERANCE)


def test_check_valid_topology_raises_on_micro_gap_even_when_scoped():
    """A gap at/below SNAP_TOLERANCE must still raise: only wider gaps are tolerated."""
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        _write_polygon_with_hole(conn, hole_width=SNAP_TOLERANCE / 2)
        with pytest.raises(RuntimeError, match="GAPS"):
            check_valid_topology(conn, "synth", gap_maximum_width=SNAP_TOLERANCE)


def test_check_valid_topology_tolerates_wide_gap_when_scoped():
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        _write_polygon_with_hole(conn, hole_width=2.0)
        check_valid_topology(conn, "synth", gap_maximum_width=SNAP_TOLERANCE)


def test_count_gaps_respects_min_width():
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        _write_polygon_with_hole(conn, hole_width=2.0)
        assert count_gaps(conn, "synth") == 1
        assert count_gaps(conn, "synth", min_width=SNAP_TOLERANCE) == 1
        assert count_gaps(conn, "synth", min_width=3.0) == 0
