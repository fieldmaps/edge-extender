"""Portability smoke tests: does clip() run to completion on this machine.

Not a topology/correctness suite -- outputs.main already raises RuntimeError
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

# Both children massively overshoot their assigned parent -- clip must bound
# each one down to exactly that parent's own extent.
_CHILD_ROWS = [
    (1, 1, "POLYGON((-5 -5, 5 -5, 5 5, -5 5, -5 -5))"),
    (2, 2, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))"),
]

_PARENT_A_AREA = 9.0

_STEPS = ["inputs", "clip", "outputs"]


def _write_parents(path, wkt_rows):
    values = ", ".join(f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in wkt_rows)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")


def _write_children(path, rows):
    values = ", ".join(
        f"({fid}, {parent_fid}, ST_GeomFromText('{wkt}'))"
        for fid, parent_fid, wkt in rows
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"""--sql
            CREATE TABLE synth AS
            SELECT * FROM (VALUES {values}) AS t(id, parent_fid, geom)
        """)
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
    assert "already-assigned parent" in result.output
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


def test_clip_requires_parent_fid_column(synthetic_parents, tmp_path):
    no_parent_fid_path = tmp_path / "no_parent_fid.parquet"
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("""--sql
            CREATE TABLE synth AS
            SELECT 1 AS id,
                   ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))') AS geom
        """)
        conn.execute(f"COPY synth TO '{no_parent_fid_path}'")

    output_path = tmp_path / "out.parquet"
    with pytest.raises(ValueError, match="parent_fid"):
        clip(no_parent_fid_path, synthetic_parents, output_path, overwrite=True)


def test_clip_raises_on_unknown_parent_fid(synthetic_parents, tmp_path):
    bad_children_path = tmp_path / "bad_children.parquet"
    _write_children(bad_children_path, [(1, 99, "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")])

    output_path = tmp_path / "out.parquet"
    with pytest.raises(RuntimeError, match="parent_fid=99"):
        clip(bad_children_path, synthetic_parents, output_path, overwrite=True)


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
