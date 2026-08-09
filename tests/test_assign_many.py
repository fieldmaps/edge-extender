"""Portability smoke tests: does assign_many() run to completion on this machine.

Not a topology/correctness suite: assignment is deterministic SQL, so a
run that completes without raising has already been vetted for correctness.
"""

import logging

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.assign_many import assign_many
from topo_tools.cli.main import cli

# Child 1 tiles Parent A alone; child 2 straddles both but overlaps B more
# (area 6 vs 4.5), so assign-many (deciding per child, not per file)
# must pick B for it even though child 1 is in the same file and prefers A.
_CHILD_WKT = [
    (1, "POLYGON((-5 -5, 1.5 -5, 1.5 5, -5 5, -5 -5))"),
    (2, "POLYGON((1.5 -5, 12 -5, 12 5, 1.5 5, 1.5 -5))"),
    (3, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))"),
    (4, "POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))"),
]
_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))"),
]

_STEPS = ["inputs", "assign", "outputs"]


def _write_synthetic(path, wkt_rows):
    values = ", ".join(f"({fid}, ST_GeomFromText('{wkt}'))" for fid, wkt in wkt_rows)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t(id, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")


@pytest.fixture
def synthetic_children(tmp_path):
    path = tmp_path / "children.parquet"
    _write_synthetic(path, _CHILD_WKT)
    return path


@pytest.fixture
def synthetic_parents(tmp_path):
    path = tmp_path / "parents.parquet"
    _write_synthetic(path, _PARENT_WKT)
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["assign-many", "--help"])
    assert result.exit_code == 0
    assert "Crosswalk each child" in result.output
    assert "Examples:" in result.output


def test_assign_many_per_child_plurality(
    synthetic_children, synthetic_parents, tmp_path
):
    """Each child picks its own largest-overlap parent, ignoring its file's siblings."""
    output_path = tmp_path / "out.parquet"
    assign_many(synthetic_children, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(f"""--sql
            SELECT id, parent_fid FROM '{output_path}' ORDER BY id
        """).fetchall()
    assert rows == [(1, 1), (2, 2), (3, 2)]


def test_assign_many_issues_file_records_unassigned(
    synthetic_children, synthetic_parents, tmp_path, caplog
):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    with caplog.at_level(logging.WARNING):
        assign_many(
            synthetic_children,
            synthetic_parents,
            output_path,
            issues_path,
            overwrite=True,
        )

    assert any("dropping" in r.message and "4" in r.message for r in caplog.records)
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        fids = [
            row[0]
            for row in conn.execute(f"SELECT child_fid FROM '{issues_path}'").fetchall()
        ]
    assert fids == [4]


def test_assign_many_default_output_path(synthetic_children, synthetic_parents):
    assign_many(synthetic_children, synthetic_parents, overwrite=True)

    expected = synthetic_children.with_stem(synthetic_children.stem + "_assigned")
    assert expected.exists()


def test_cli_positional_args(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "assign-many",
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
            "assign-many",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
        ],
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_assign_many_steps(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        assign_many(
            synthetic_children,
            synthetic_parents,
            output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()
