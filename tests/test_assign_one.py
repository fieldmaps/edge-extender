"""Portability smoke tests: does assign_one() run to completion on this machine.

Not a topology/correctness suite: assignment is deterministic SQL, so a
run that completes without raising has already been vetted for correctness.
"""

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.assign_one import assign_one
from topo_tools.cli.main import cli

_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))"),
]

# file_a tiles Parent A at x=1.5, but child 2 straddles into Parent B with a
# bigger individual overlap there (area 6 vs 4.5); its own plurality would
# pick B, but file_a's vote count (2 children touch A, 1 touches B) must
# still pick A for every child in the file. file_b's only child touches B
# alone, so its file trivially votes for B.
_CHILD_A = (1, "POLYGON((-5 -5, 1.5 -5, 1.5 5, -5 5, -5 -5))")
_CHILD_STRADDLE = (2, "POLYGON((1.5 -5, 12 -5, 12 5, 1.5 5, 1.5 -5))")
_CHILD_B_ONLY = (3, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))")
_CHILD_UNREACHABLE = (4, "POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))")

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
def synthetic_parents(tmp_path):
    path = tmp_path / "parents.parquet"
    _write_synthetic(path, _PARENT_WKT)
    return path


@pytest.fixture
def synthetic_children_split(tmp_path):
    """file_a (children 1, 2) votes for Parent A; file_b (child 3) votes for B."""
    path_a = tmp_path / "file_a.parquet"
    path_b = tmp_path / "file_b.parquet"
    _write_synthetic(path_a, [_CHILD_A, _CHILD_STRADDLE])
    _write_synthetic(path_b, [_CHILD_B_ONLY])
    return [path_a, path_b]


def test_cli_help():
    result = CliRunner().invoke(cli, ["assign-one", "--help"])
    assert result.exit_code == 0
    assert "Crosswalk a multi-file child set" in result.output
    assert "Examples:" in result.output


def test_assign_one_file_majority_overrides_per_child_plurality(
    synthetic_children_split, synthetic_parents, tmp_path
):
    output_path = tmp_path / "out.parquet"
    assign_one(synthetic_children_split, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(f"""--sql
            SELECT id, parent_fid FROM '{output_path}' ORDER BY id
        """).fetchall()
    assert rows == [(1, 1), (2, 1), (3, 2)]


def test_assign_one_issues_file_records_unassigned_file(
    synthetic_children_split, synthetic_parents, tmp_path
):
    """A file whose only child overlaps nothing is entirely unassigned."""
    unreachable_path = tmp_path / "file_c.parquet"
    _write_synthetic(unreachable_path, [_CHILD_UNREACHABLE])

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    assign_one(
        [*synthetic_children_split, unreachable_path],
        synthetic_parents,
        output_path,
        issues_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        fids = [
            row[0]
            for row in conn.execute(f"SELECT child_fid FROM '{issues_path}'").fetchall()
        ]
    assert fids == [4]


def test_assign_one_single_file(synthetic_parents, tmp_path):
    """A single input file still needs output_path defaulted from it."""
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_A, _CHILD_STRADDLE])

    assign_one(children_path, synthetic_parents, overwrite=True)

    expected = children_path.with_stem(children_path.stem + "_assigned")
    assert expected.exists()


def test_output_path_required_for_multiple_files(
    synthetic_children_split, synthetic_parents
):
    with pytest.raises(ValueError, match="output_path is required"):
        assign_one(synthetic_children_split, synthetic_parents)


def test_cli_positional_args(
    synthetic_children_split,  # noqa: ARG001 (write side effect is the point)
    synthetic_parents,
    tmp_path,
):
    glob_pattern = str(tmp_path / "file_*.parquet")
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli, ["assign-one", glob_pattern, str(synthetic_parents), str(output_path)]
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_error_on_existing_output(
    synthetic_children_split,  # noqa: ARG001 (write side effect is the point)
    synthetic_parents,
    tmp_path,
):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    glob_pattern = str(tmp_path / "file_*.parquet")
    result = CliRunner().invoke(
        cli, ["assign-one", glob_pattern, str(synthetic_parents), str(output_path)]
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_assign_one_steps(synthetic_children_split, synthetic_parents, tmp_path):
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        assign_one(
            synthetic_children_split,
            synthetic_parents,
            output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()
