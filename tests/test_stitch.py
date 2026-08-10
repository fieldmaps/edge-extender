"""Portability smoke tests: does stitch() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on coverage violations, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.stitch import stitch
from topo_tools.cli.main import cli

_STEPS = ["inputs", "clean", "outputs"]


def _frame_wkt(gap: float) -> list[tuple[int, str]]:
    """Build four rectangles framing a gap x gap hole at (1,1)-(1+gap,1+gap)."""
    g, top = gap, 2 + gap
    return [
        (1, f"POLYGON((0 0, 1 0, 1 {top}, 0 {top}, 0 0))"),
        (2, f"POLYGON(({1 + g} 0, {top} 0, {top} {top}, {1 + g} {top}, {1 + g} 0))"),
        (3, f"POLYGON((1 0, {1 + g} 0, {1 + g} 1, 1 1, 1 0))"),
        (
            4,
            f"POLYGON((1 {1 + g}, {1 + g} {1 + g}, {1 + g} {top}, 1 {top}, 1 {1 + g}))",
        ),
    ]


def _write_synthetic(path, wkt_rows) -> None:
    values = ", ".join(f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in wkt_rows)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")


@pytest.fixture
def tiny_gap_input(tmp_path):
    """Build a frame with a gap far smaller than SNAP_TOLERANCE, closeable by stitch."""
    path = tmp_path / "tiny_gap.parquet"
    _write_synthetic(path, _frame_wkt(1e-9))
    return path


@pytest.fixture
def large_gap_input(tmp_path):
    """Build a frame with a gap too large for stitch to close (SNAP_TOLERANCE)."""
    path = tmp_path / "large_gap.parquet"
    _write_synthetic(path, _frame_wkt(0.5))
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["stitch", "--help"])
    assert result.exit_code == 0
    assert "Close seams" in result.output
    assert "Examples:" in result.output


def test_stitch_closes_small_seam_gap(tiny_gap_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    stitch(tiny_gap_input, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    assert not issues_path.exists()
    expected_row_count = 4
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count


def test_stitch_tolerates_unclosed_gap(large_gap_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    stitch(large_gap_input, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    expected_row_count = 4
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
        gap_rows = conn.execute(
            f"SELECT max_width_m FROM '{issues_path}' WHERE kind = 'gap'"
        ).fetchall()
    assert row_count == expected_row_count
    assert len(gap_rows) == 1
    assert gap_rows[0][0] > 0


def test_stitch_default_output_path(tiny_gap_input):
    stitch(tiny_gap_input, overwrite=True)

    expected = tiny_gap_input.with_stem(tiny_gap_input.stem + "_stitched")
    assert expected.exists()


def test_cli_positional_args(tiny_gap_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(cli, ["stitch", str(tiny_gap_input), str(output_path)])
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_issues_file_option(large_gap_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    issues_path = tmp_path / "cli_issues.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "stitch",
            str(large_gap_input),
            str(output_path),
            "--issues-file",
            str(issues_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert issues_path.exists()


def test_cli_clean_error_on_existing_output(tiny_gap_input, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(cli, ["stitch", str(tiny_gap_input), str(output_path)])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "output already exists" in result.output


def test_stitch_steps(tiny_gap_input, tmp_path):
    """Each pipeline stage runs standalone, reusing one tmp_dir's DuckDB file."""
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        stitch(tiny_gap_input, output_path, tmp_dir=work_dir, step=step, overwrite=True)
    assert output_path.exists()
