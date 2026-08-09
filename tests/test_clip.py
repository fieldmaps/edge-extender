"""Portability smoke tests: does clip() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on an empty result, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.clip import clip
from topo_tools.cli.main import cli

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
    result = CliRunner().invoke(cli, ["clip", "--help"])
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
        ["clip", str(synthetic_children), str(synthetic_parents), str(output_path)],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_error_on_existing_output(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        ["clip", str(synthetic_children), str(synthetic_parents), str(output_path)],
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
