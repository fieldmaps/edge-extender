"""Portability smoke tests: does clean() run to completion on this machine.

Not a topology/correctness suite for the general pipeline, but the gap/
overlap *classification* logic is new and non-obvious enough (see
core/clean/_02_issues.py) that a few of these tests do assert on specific
detected/fixed outcomes, not just "did it run."
"""

import duckdb
import pytest
from click.testing import CliRunner

import topo_tools.core.clean._03_clean as clean_stage
from topo_tools.api.clean import clean
from topo_tools.cli.main import cli
from topo_tools.core.clean._constants import GAP_WIDTH_ESCALATION_FACTORS

# Two independent groups, spatially separated so each exercises exactly one
# defect kind without interference:
#   - fid 1-4: a "donut" of four polygons noded at their shared corners,
#     enclosing a real 1x1 degree gap at (1,1)-(2,2). Enclosure matters --
#     an open inlet between two non-surrounding polygons is NOT detected as
#     a gap by the interior-ring method (GEOS: "gaps not fully enclosed are
#     not removed").
#   - fid 5-6: fid 6 overlaps fid 5 by 0.05 degrees.
#   - fid 7-8: fid 8 sits fully inside fid 7 (a duplicated/nested-digitizing
#     defect). The overlap join's predicate is ST_Overlaps OR ST_Contains,
#     not ST_Intersects -- ST_Overlaps alone is false here by OGC definition
#     (the intersection equals fid 8 exactly, not "different from both
#     inputs"), so this pair only gets caught via the ST_Contains half.
#   - fid 9-12: a second donut, enclosing a 10x0.1 sliver-shaped gap at
#     (51,1)-(61,1.1) -- same area (1.0) as the fid 1-4 hole but a thinness
#     ratio (~0.03) far below DEFAULT_THINNESS_RATIO, unlike fid 1-4's square
#     hole (~0.785). Distinguishes --maximum-gap-width=auto's shape-based
#     fill from the compact hole it must leave alone.
_SYNTHETIC_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 1, 2 1, 1 1, 0 1, 0 0))"),
    (2, "POLYGON((0 2, 1 2, 2 2, 3 2, 3 3, 0 3, 0 2))"),
    (3, "POLYGON((0 1, 1 1, 1 2, 0 2, 0 1))"),
    (4, "POLYGON((2 1, 3 1, 3 2, 2 2, 2 1))"),
    (5, "POLYGON((10 0, 11 0, 11 1, 10 1, 10 0))"),
    (6, "POLYGON((10.95 0, 12 0, 12 1, 10.95 1, 10.95 0))"),
    (7, "POLYGON((30 0, 32 0, 32 2, 30 2, 30 0))"),
    (8, "POLYGON((30.5 0.5, 31.5 0.5, 31.5 1.5, 30.5 1.5, 30.5 0.5))"),
    (9, "POLYGON((50 0, 62 0, 62 1, 50 1, 50 0))"),
    (10, "POLYGON((50 1.1, 62 1.1, 62 2.1, 50 2.1, 50 1.1))"),
    (11, "POLYGON((50 1, 51 1, 51 1.1, 50 1.1, 50 1))"),
    (12, "POLYGON((61 1, 62 1, 62 1.1, 61 1.1, 61 1))"),
]

_STEPS = ["inputs", "issues", "clean", "outputs"]


@pytest.fixture
def synthetic_input(tmp_path):
    """Write a small synthetic GeoParquet -- no real-world fixture needed."""
    path = tmp_path / "synthetic.parquet"
    values = ", ".join(
        f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in _SYNTHETIC_WKT
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")
    return path


def _real_hole_area(path):
    """Area of any fully-enclosed hole in the union of an output file's polygons."""
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        return conn.execute(f"""
            WITH u AS (SELECT ST_Union_Agg(geometry) AS g FROM '{path}'),
            parts AS (SELECT (UNNEST(ST_Dump(g))).geom AS geom FROM u)
            SELECT COALESCE(
                SUM(
                    ST_Area(ST_Difference(ST_MakePolygon(ST_ExteriorRing(geom)), geom))
                ),
                0
            )
            FROM parts WHERE ST_NumInteriorRings(geom) > 0
        """).fetchone()[0]


def test_cli_help():
    result = CliRunner().invoke(cli, ["clean", "--help"])
    assert result.exit_code == 0
    assert "Detect and fix gap/overlap defects" in result.output
    assert "Examples:" in result.output


def test_clean_full_run(synthetic_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    clean(synthetic_input, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    assert issues_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
        kinds = {
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT kind FROM '{issues_path}'"
            ).fetchall()
        }
    assert row_count == len(_SYNTHETIC_WKT)
    assert kinds == {"gap", "overlap"}


def test_clean_detects_full_containment_overlap(synthetic_input, tmp_path):
    """A fully-nested duplicate polygon (id 8 inside id 7) is an overlap.

    Regression for the overlap join predicate: ST_Overlaps alone is false
    for full containment (OGC: the intersection must differ from both
    inputs), so this only gets caught via the ST_Contains half. Located by
    geometry, not unit_a/unit_b -- those reference the internal `fid`
    (row_number() over an unordered scan, since preserve_insertion_order is
    off), which isn't guaranteed to match the source "id" column.
    """
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    clean(synthetic_input, output_path, issues_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        area = conn.execute(f"""
            SELECT ST_Area(geometry) FROM '{issues_path}'
            WHERE kind = 'overlap'
              AND ST_Within(geometry, ST_MakeEnvelope(30, 0, 32, 2))
        """).fetchall()
    # Full containment -- the overlap area equals fid 8's entire 1x1 extent.
    assert area == [(1.0,)]


def test_clean_default_output_paths(synthetic_input):
    clean(synthetic_input, overwrite=True)

    expected_output = synthetic_input.with_stem(synthetic_input.stem + "_cleaned")
    expected_issues = expected_output.with_stem(expected_output.stem + "_issues")
    assert expected_output.exists()
    assert expected_issues.exists()


@pytest.fixture
def scaled_gap_input(tmp_path):
    """Write a single compact 1x1 hole inside a ~10,200-area ring, not ~8.

    `_SYNTHETIC_WKT`'s fid 1-4 group makes its hole a huge (12.5%) fraction
    of the surrounding ring's own area -- fine for the thin-vs-compact shape
    tests, but unrepresentative of real admin-boundary data (where the
    widest gap is a tiny fraction of its surroundings) and it triggers a
    real `ST_CoverageClean` defect when combined with fid 9-12's
    differently-scaled group in the same call: several unrelated polygons
    collapse to zero area, confirmed to not happen with either group
    processed alone. This fixture keeps the hole's shape/width identical
    (still 1x1, same ~0.785 thinness) so `--maximum-gap-width` assertions
    stay valid, just embedded in a realistically-scaled, single-group ring.
    """
    path = tmp_path / "scaled_gap.parquet"
    wkt = [
        (1, "POLYGON((0 0, 101 0, 101 50, 0 50, 0 0))"),
        (2, "POLYGON((0 51, 101 51, 101 101, 0 101, 0 51))"),
        (3, "POLYGON((0 50, 50 50, 50 51, 0 51, 0 50))"),
        (4, "POLYGON((51 50, 101 50, 101 51, 51 51, 51 50))"),
    ]
    values = ", ".join(f"({fid}, ST_GeomFromText('{w}'))" for fid, w in wkt)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")
    return path


@pytest.fixture
def gap_only_input(tmp_path):
    """Write a ring of 4 polygons enclosing a 1x1 hole, with no overlaps anywhere.

    Fully noded (each neighbor's shared corner is an explicit vertex on the
    other's ring, same style as `_SYNTHETIC_WKT`'s fid 1-4 group) and scaled
    so the hole is a small fraction of the ring (same reasoning as
    `scaled_gap_input`), so `has_coverage_violations()`
    (`ST_CoverageInvalidEdges_Agg`) is False -- confirmed directly -- without
    tripping the area-erosion instability a non-noded or too-small-scale
    fixture hits. Regression fixture for `_03_clean.py`'s fix stage: it used
    to gate the whole `ST_CoverageClean` call on `has_coverage_violations()`,
    which only detects overlaps/mismatched edges, never gaps -- silently
    no-opping on exactly this shape of input.
    """
    path = tmp_path / "gap_only.parquet"
    wkt = [
        (1, "POLYGON((0 0, 101 0, 101 50, 51 50, 50 50, 0 50, 0 0))"),
        (2, "POLYGON((0 51, 50 51, 51 51, 101 51, 101 101, 0 101, 0 51))"),
        (3, "POLYGON((0 50, 50 50, 50 51, 0 51, 0 50))"),
        (4, "POLYGON((51 50, 101 50, 101 51, 51 51, 51 50))"),
    ]
    values = ", ".join(f"({fid}, ST_GeomFromText('{w}'))" for fid, w in wkt)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")
    return path


def test_clean_fills_gap_with_no_coverage_violations(gap_only_input, tmp_path):
    """`--maximum-gap-width all` must still fill a gap when nothing overlaps.

    Regression for the `_03_clean.py` gate bug: has_coverage_violations()
    is False for this fixture (no overlaps/mismatched edges), but a real
    fully-enclosed gap exists and must still get filled.
    """
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        violations = conn.execute(f"""
            SELECT ST_CoverageInvalidEdges_Agg(geom) IS NOT NULL
            FROM (SELECT UNNEST(ST_Dump(geom)).geom AS geom FROM '{gap_only_input}')
        """).fetchone()[0]
    assert violations is False

    output_path = tmp_path / "gap_only_cleaned.parquet"
    issues_path = tmp_path / "gap_only_issues.parquet"
    clean(
        gap_only_input,
        output_path,
        issues_path,
        maximum_gap_width="all",
        overwrite=True,
    )

    assert _real_hole_area(output_path) == pytest.approx(0.0, abs=1e-9)


def test_clean_maximum_gap_width_all_fills_gap(scaled_gap_input, tmp_path):
    output_path = tmp_path / "all.parquet"
    issues_path = tmp_path / "all_issues.parquet"
    clean(
        scaled_gap_input,
        output_path,
        issues_path,
        maximum_gap_width="all",
        overwrite=True,
    )

    assert _real_hole_area(output_path) == pytest.approx(0.0, abs=1e-9)


def test_clean_maximum_gap_width_auto_fills_only_thin_gap(synthetic_input, tmp_path):
    """Auto fills the fid 9-12 sliver but leaves the fid 1-4 compact square alone."""
    output_path = tmp_path / "auto.parquet"
    issues_path = tmp_path / "auto_issues.parquet"
    clean(
        synthetic_input,
        output_path,
        issues_path,
        maximum_gap_width="auto",
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        compact_filled, thin_filled = conn.execute(f"""
            WITH u AS (SELECT ST_Union_Agg(geometry) AS g FROM '{output_path}')
            SELECT ST_Contains(u.g, ST_Point(1.5, 1.5)),
                   ST_Contains(u.g, ST_Point(55, 1.05))
            FROM u
        """).fetchone()
    assert compact_filled is False
    assert thin_filled is True


def test_clean_maximum_gap_width_explicit_degrees(scaled_gap_input, tmp_path):
    narrow_output = tmp_path / "narrow.parquet"
    narrow_issues = tmp_path / "narrow_issues.parquet"
    clean(
        scaled_gap_input,
        narrow_output,
        narrow_issues,
        maximum_gap_width="0.5",
        overwrite=True,
    )
    # 0.5 degrees doesn't clear the compact square's ~1 degree MIC width,
    # so the hole (area 1.0) remains.
    assert _real_hole_area(narrow_output) == pytest.approx(1.0, rel=1e-6)

    wide_output = tmp_path / "wide.parquet"
    wide_issues = tmp_path / "wide_issues.parquet"
    clean(
        scaled_gap_input,
        wide_output,
        wide_issues,
        maximum_gap_width="2",
        overwrite=True,
    )
    assert _real_hole_area(wide_output) == pytest.approx(0.0, abs=1e-9)


def test_clean_invalid_maximum_gap_width_value(synthetic_input, tmp_path):
    with pytest.raises(ValueError, match="maximum-gap-width"):
        clean(
            synthetic_input,
            tmp_path / "bad.parquet",
            maximum_gap_width="potato",
            overwrite=True,
        )


def _overlapping_pair_conn():
    """Open a connection with a minimal 2-fid overlapping `stage_01` table."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    conn.execute("""
        CREATE TABLE stage_01 AS
        SELECT * FROM (VALUES
            (1, ST_GeomFromText('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))')),
            (2, ST_GeomFromText('POLYGON((1 1, 3 1, 3 3, 1 3, 1 1))'))
        ) AS t(fid, geom)
    """)
    return conn


def test_clean_gap_width_escalation_recovers_after_transient_failures(monkeypatch):
    """The escalation loop moves past a rung that fails outright and succeeds later.

    The first rung fails here, so recovery lands on the second rung -- the
    second `coverage_clean` call overall.
    """
    expected_row_count = 2
    recovery_call_count = 2
    calls = []
    real_coverage_clean = clean_stage.coverage_clean

    def flaky_coverage_clean(conn, table_in, table_out, **kwargs):
        calls.append(kwargs["gap_maximum_width"])
        if len(calls) < recovery_call_count:
            msg = "simulated GEOS instability at this width"
            raise RuntimeError(msg)
        real_coverage_clean(conn, table_in, table_out, **kwargs)

    monkeypatch.setattr(clean_stage, "coverage_clean", flaky_coverage_clean)

    with _overlapping_pair_conn() as conn:
        clean_stage.main(
            conn,
            "stage",
            gap_maximum_width=("value", 0.5),
            snapping_distance=("auto", None),
        )
        row_count = conn.execute("SELECT COUNT(*) FROM stage_03").fetchone()[0]

    assert row_count == expected_row_count
    assert len(calls) == recovery_call_count


def test_clean_gap_width_escalation_exhausted_raises(monkeypatch):
    """Every rung failing raises a clear error instead of silently degrading."""
    calls = []

    def always_fails(*_args, **kwargs):
        calls.append(kwargs["gap_maximum_width"])
        msg = "simulated persistent GEOS instability"
        raise RuntimeError(msg)

    monkeypatch.setattr(clean_stage, "coverage_clean", always_fails)

    with (
        _overlapping_pair_conn() as conn,
        pytest.raises(RuntimeError, match="escalation exhausted"),
    ):
        clean_stage.main(
            conn,
            "stage",
            gap_maximum_width=("value", 0.5),
            snapping_distance=("auto", None),
        )

    assert len(calls) == len(GAP_WIDTH_ESCALATION_FACTORS)


def test_clean_gap_width_escalation_rejects_eroded_output(monkeypatch):
    """A totally empty coverage_clean() result must not be accepted as success.

    Regression: has_coverage_violations() alone passes an empty result as
    "no violations" -- confirmed directly against a real ST_CoverageClean
    call at a large gap_maximum_width that silently erased all polygon
    area. The escalation loop must also reject on the area-sanity check,
    not just the invalid-edges check, so a call that "succeeds" by
    returning nothing still counts as this rung failing.
    """

    def empties_output(conn, table_in, table_out, **_kwargs):
        query = (
            f'CREATE OR REPLACE TABLE "{table_out}" AS '
            f'SELECT * FROM "{table_in}" WHERE FALSE'
        )
        conn.execute(query)

    monkeypatch.setattr(clean_stage, "coverage_clean", empties_output)

    with (
        _overlapping_pair_conn() as conn,
        pytest.raises(RuntimeError, match="escalation exhausted"),
    ):
        clean_stage.main(
            conn,
            "stage",
            gap_maximum_width=("value", 0.5),
            snapping_distance=("auto", None),
        )


def test_cli_positional_args(synthetic_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(cli, ["clean", str(synthetic_input), str(output_path)])
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_clean_error_on_existing_output(synthetic_input, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(cli, ["clean", str(synthetic_input), str(output_path)])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "output already exists" in result.output


def test_clean_steps(synthetic_input, tmp_path):
    """Each pipeline stage runs standalone, reusing one tmp_dir's DuckDB file."""
    output_path = tmp_path / "steps_out.parquet"
    issues_path = tmp_path / "steps_issues.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        clean(
            synthetic_input,
            output_path,
            issues_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()
    assert issues_path.exists()
