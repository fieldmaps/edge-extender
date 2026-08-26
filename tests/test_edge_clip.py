"""Portability smoke tests: does clip() run to completion on this machine.

Not a correctness suite: outputs.main already raises RuntimeError on an
empty result, so a clean run is already vetted by the pipeline itself.
"""

import math

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.edge_clip import clip
from topo_tools.cli.main import cli
from topo_tools.core.constants import CLIP_TILE_MIN_VERTICES

_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))"),
]

# Overshoots parent A's extent only, no overlap with parent B.
_CHILD_ROWS = [(1, "POLYGON((-5 -5, 5 -5, 5 5, -5 5, -5 -5))")]

_PARENT_A_AREA = 9.0

_STEPS = ["inputs", "assign", "clip", "outputs"]


def _write_parents(path, wkt_rows):
    values = ", ".join(f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in wkt_rows)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")


def _write_children(path, wkt_rows):
    values = ", ".join(f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in wkt_rows)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")


@pytest.fixture
def synthetic_parents(tmp_path):
    path = tmp_path / "parents.parquet"
    _write_parents(path, _PARENT_WKT)
    return path


@pytest.fixture
def synthetic_children(tmp_path):
    path = tmp_path / "children.parquet"
    _write_children(path, _CHILD_ROWS)
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["edge-clip", "--help"])
    assert result.exit_code == 0
    assert "assign-one" in result.output
    assert "Examples:" in result.output


def test_clip_bounds_output_to_parent(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "out.parquet"
    clip(synthetic_children, synthetic_parents, output_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        area = conn.execute(f"""--sql
            SELECT ST_Area(geometry) FROM '{output_path}' WHERE id = 1
        """).fetchone()[0]
    assert area == pytest.approx(_PARENT_A_AREA, abs=1e-6)


def test_clip_majority_vote_drops_outlier(synthetic_parents, tmp_path):
    """Two children overshoot parent A, one overshoots parent B.

    A wins the file's majority vote; the dissenting child is dropped, not misassigned.
    """
    children_path = tmp_path / "children.parquet"
    _write_children(
        children_path,
        [
            (1, "POLYGON((-5 -5, 5 -5, 5 5, -5 5, -5 -5))"),
            (2, "POLYGON((-2 -2, 4 -2, 4 4, -2 4, -2 -2))"),
            (3, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))"),
        ],
    )

    output_path = tmp_path / "out.parquet"
    clip(children_path, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(f"""--sql
            SELECT id, ST_Area(geometry) FROM '{output_path}' ORDER BY id
        """).fetchall()
    assert [r[0] for r in rows] == [1, 2]
    assert all(area == pytest.approx(_PARENT_A_AREA, abs=1e-6) for _, area in rows)


def _circle_wkt(cx, cy, r, n):
    pts = [
        (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    pts.append(pts[0])
    coords = ", ".join(f"{x} {y}" for x, y in pts)
    return f"POLYGON(({coords}))"


def test_clip_heavy_parent_tiling_finds_real_overlap(tmp_path):
    """A parent part at/above CLIP_TILE_MIN_VERTICES takes assign-one's grid-tiled path.

    Regression test: a heavy tile's bbox columns must survive the join
    that finds its real overlaps.
    """
    n_points = CLIP_TILE_MIN_VERTICES + 200
    parents_path = tmp_path / "heavy_parents.parquet"
    _write_parents(parents_path, [(1, _circle_wkt(50, 50, 10, n_points))])

    children_path = tmp_path / "heavy_children.parquet"
    _write_children(
        children_path, [(1, "POLYGON((49 49, 51 49, 51 51, 49 51, 49 49))")]
    )

    output_path = tmp_path / "out.parquet"
    clip(children_path, parents_path, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert count == 1


def test_clip_raises_when_no_child_overlaps_any_parent(synthetic_parents, tmp_path):
    children_path = tmp_path / "children.parquet"
    _write_children(
        children_path, [(1, "POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))")]
    )

    output_path = tmp_path / "out.parquet"
    with pytest.raises(RuntimeError, match="no child survived clipping"):
        clip(children_path, synthetic_parents, output_path, overwrite=True)


def test_clip_default_output_path(synthetic_children, synthetic_parents):
    clip(synthetic_children, synthetic_parents, overwrite=True)

    expected = synthetic_children.with_stem(synthetic_children.stem + "_clipped")
    assert expected.exists()


def test_cli_positional_args(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-clip",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_error_on_existing_output(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        [
            "edge-clip",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
            "--overwrite=false",
        ],
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_clip_steps(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        clip(
            synthetic_children,
            synthetic_parents,
            output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()


def test_cli_single_file_unchanged(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-clip",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        area = conn.execute(f"""--sql
            SELECT ST_Area(geometry) FROM '{output_path}' WHERE id = 1
        """).fetchone()[0]
    assert area == pytest.approx(_PARENT_A_AREA, abs=1e-6)


def _write_with_code(path, rows):
    """rows: list of (fid, wkt, pcode)."""
    values = ", ".join(
        f"({fid}, ST_GeomFromText('{wkt}'), '{code}')" for fid, wkt, code in rows
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"""--sql
            CREATE TABLE synth AS
            SELECT * FROM (VALUES {values}) AS t(id, geom, pcode)
        """)
        conn.execute(f"COPY synth TO '{path}'")


def test_match_overrides_spatial_and_reports_mismatch(tmp_path):
    """A child mostly inside parent A but coded to parent B ends up clipped to B."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_with_code(
        children_path,
        # Overlaps parent A (area 2) far more than parent B (area 0.5), but
        # its code points to B, which it does overlap, so code wins.
        [(1, "POLYGON((1 0, 10.5 0, 10.5 1, 1 1, 1 0))", "P2")],
    )

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    clip(
        children_path,
        parents_path,
        output_path,
        issues_path,
        match_column="pcode",
        overwrite=True,
    )

    assert output_path.exists()
    assert issues_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        area = conn.execute(
            f"SELECT ST_Area(geometry) FROM '{output_path}'"
        ).fetchone()[0]
        kinds = [
            row[0]
            for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
        ]
    # Clipped to parent B (only the child's x:10-10.5 sliver survives), not
    # parent A, where clipping would have kept the much larger x:1-3 slice.
    assert area == pytest.approx(0.5, abs=1e-6)
    assert kinds == ["code-mismatch"]


def test_match_falls_back_when_code_unmatched(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")],
    )
    children_path = tmp_path / "children.parquet"
    _write_with_code(
        children_path,
        [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))", "NOPE")],
    )

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    clip(
        children_path,
        parents_path,
        output_path,
        issues_path,
        match_column="pcode",
        overwrite=True,
    )

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        kinds = [
            row[0]
            for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
        ]
    assert kinds == ["code-fallback"]


def test_match_mutually_exclusive_with_pair(
    synthetic_children, synthetic_parents, tmp_path
):
    with pytest.raises(ValueError, match="mutually exclusive"):
        clip(
            synthetic_children,
            synthetic_parents,
            tmp_path / "out.parquet",
            match_column="pcode",
            parent_match_column="pcode",
        )


def test_cli_match_help():
    result = CliRunner().invoke(cli, ["edge-clip", "--help"])
    assert result.exit_code == 0
    assert "--match-column" in result.output
    assert "--parent-match-column" in result.output
    assert "--child-match-column" in result.output


def test_clip_carry_columns_populates_output(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")])
    children_path = tmp_path / "children.parquet"
    _write_children(
        children_path, [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))")]
    )

    output_path = tmp_path / "out.parquet"
    clip(
        children_path,
        parents_path,
        output_path,
        carry_columns=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        pcode = conn.execute(f"SELECT pcode FROM '{output_path}'").fetchone()[0]
    assert pcode == "P1"


def test_cli_carry_column_help():
    result = CliRunner().invoke(cli, ["edge-clip", "--help"])
    assert result.exit_code == 0
    assert "--carry-column" in result.output
