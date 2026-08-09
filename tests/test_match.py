"""Portability smoke tests: does match() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on coverage violations, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import logging

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.match import match
from topo_tools.cli.main import cli
from topo_tools.core.match import _04_clip as match_clip
from topo_tools.core.match._03_groups import _record_dropped_group

# Parent A (large square) contains children 1 & 2 with a gap between them,
# exercises multi-child grouping, within-group Voronoi fill, and clip-to-
# parent. Parent B (disjoint large square) contains only child 3 alone,
# exercises the "always group, even size 1" path. Child 4 sits far outside
# both parents, exercises the drop-unmatched-with-a-warning path.
_CHILD_WKT = [
    (1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))"),
    (2, "POLYGON((1.5 0.5, 2 0.5, 2 1, 1.5 1, 1.5 0.5))"),
    (3, "POLYGON((11 1, 12 1, 12 2, 11 2, 11 1))"),
    (4, "POLYGON((20 0, 21 0, 21 1, 20 1, 20 0))"),
]
_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))"),
]

_STEPS = ["inputs", "assign", "groups", "clip", "stitch", "outputs"]


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
    """Write a small synthetic child-layer GeoParquet, no real-world fixture."""
    path = tmp_path / "children.parquet"
    _write_synthetic(path, _CHILD_WKT)
    return path


@pytest.fixture
def synthetic_parents(tmp_path):
    """Write a small synthetic parent/clip-layer GeoParquet."""
    path = tmp_path / "parents.parquet"
    _write_synthetic(path, _PARENT_WKT)
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["match", "--help"])
    assert result.exit_code == 0
    assert "Match children to parents" in result.output
    assert "Examples:" in result.output


def test_match_full_run(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "out.parquet"
    match(synthetic_children, synthetic_parents, output_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT id FROM '{output_path}' ORDER BY id"
            ).fetchall()
        ]
    assert ids == [1, 2, 3]


def test_match_drops_unassigned_and_warns(
    synthetic_children, synthetic_parents, tmp_path, caplog
):
    output_path = tmp_path / "out.parquet"
    with caplog.at_level(logging.WARNING):
        match(synthetic_children, synthetic_parents, output_path, overwrite=True)

    assert any("dropping" in r.message and "4" in r.message for r in caplog.records)


def test_match_issues_file_default_path(
    synthetic_children, synthetic_parents, tmp_path
):
    output_path = tmp_path / "out.parquet"
    match(synthetic_children, synthetic_parents, output_path, overwrite=True)

    expected_issues_path = output_path.with_stem(output_path.stem + "_issues")
    assert expected_issues_path.exists()


def test_match_issues_file_records_unassigned_child(
    synthetic_children, synthetic_parents, tmp_path
):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        synthetic_children,
        synthetic_parents,
        output_path,
        issues_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(f"SELECT * FROM '{issues_path}'").fetchall()
        cols = [
            d[0] for d in conn.execute(f"SELECT * FROM '{issues_path}'").description
        ]

    unassigned_child_fid = 4
    assert len(rows) == 1
    row = dict(zip(cols, rows[0], strict=True))
    assert row["kind"] == "unassigned"
    assert row["child_fid"] == unassigned_child_fid
    assert row["parent_fid"] is None
    assert row["reason"] is None
    assert row["geometry"] is not None


def test_match_issues_file_empty_when_nothing_dropped(tmp_path):
    """Parent B's single-child group succeeds cleanly, so the issues file is empty."""
    children_path = tmp_path / "children_single.parquet"
    parents_path = tmp_path / "parents_single.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[2]])  # fid 3 only
    _write_synthetic(parents_path, [_PARENT_WKT[1]])  # Parent B only

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(children_path, parents_path, output_path, issues_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        count = conn.execute(f"SELECT COUNT(*) FROM '{issues_path}'").fetchone()[0]
    assert count == 0


def test_record_dropped_group():
    """Exercises the group-failure recording helper directly, no subprocess involved."""
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("""--sql
            CREATE TABLE t_child_01 AS
            SELECT * FROM (VALUES
                (1, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
                (2, ST_GeomFromText('POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))'))
            ) AS v(fid, geom)
        """)
        conn.execute("""--sql
            CREATE TABLE t_02_assign AS
            SELECT * FROM (VALUES (1, 10), (2, 10)) AS v(child_fid, parent_fid)
        """)
        conn.execute("""--sql
            CREATE TABLE t_03b AS
            SELECT NULL::BIGINT AS child_fid, NULL::BIGINT AS parent_fid,
                   NULL::VARCHAR AS reason, NULL::GEOMETRY AS geom
            WHERE FALSE
        """)

        _record_dropped_group(conn, "t", 10, "boom: something failed")

        rows = conn.execute(
            "SELECT child_fid, parent_fid, reason FROM t_03b ORDER BY child_fid"
        ).fetchall()

    assert rows == [
        (1, 10, "boom: something failed"),
        (2, 10, "boom: something failed"),
    ]


def test_match_clip_step_aborts_on_bad_parent_fid(tmp_path):
    """A single bad parent_fid in the clip step aborts the whole run.

    Documents the accepted simplification vs. match's old per-group
    continue-past-failure behavior: clip's own hard-fail-on-first-bad-
    parent_fid semantics now apply uniformly to match too.
    """
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("""--sql
            CREATE TABLE t_03a AS
            SELECT * FROM (VALUES
                (1, 99, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'))
            ) AS v(fid, parent_fid, geom)
        """)
        conn.execute("""--sql
            CREATE TABLE t_parent_01 AS
            SELECT * FROM (VALUES
                (1, ST_GeomFromText('POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))'))
            ) AS v(fid, geom)
        """)

        with pytest.raises(RuntimeError, match="parent_fid=99"):
            match_clip.main(conn, "t", tmp_path)


def test_match_single_parent_group(tmp_path):
    """Parent B has exactly one assigned child.

    Exercises the always-group, even-size-1 path explicitly, isolated from
    Parent A's multi-child group.
    """
    children_path = tmp_path / "children_single.parquet"
    parents_path = tmp_path / "parents_single.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[2]])  # fid 3 only
    _write_synthetic(parents_path, [_PARENT_WKT[1]])  # Parent B only

    output_path = tmp_path / "out.parquet"
    match(children_path, parents_path, output_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == 1


def test_match_default_output_path(synthetic_children, synthetic_parents):
    match(synthetic_children, synthetic_parents, overwrite=True)

    expected = synthetic_children.with_stem(synthetic_children.stem + "_matched")
    assert expected.exists()


def test_cli_positional_args(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        ["match", str(synthetic_children), str(synthetic_parents), str(output_path)],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_issues_file_option(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    issues_path = tmp_path / "cli_issues.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "match",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
            "--issues-file",
            str(issues_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert issues_path.exists()


def test_cli_clip_file_required(synthetic_children):
    result = CliRunner().invoke(cli, ["match", str(synthetic_children)])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_cli_clean_error_on_existing_output(
    synthetic_children, synthetic_parents, tmp_path
):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        ["match", str(synthetic_children), str(synthetic_parents), str(output_path)],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "output already exists" in result.output


def test_match_steps(synthetic_children, synthetic_parents, tmp_path):
    """Each pipeline stage runs standalone, reusing one tmp_dir's DuckDB file."""
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        match(
            synthetic_children,
            synthetic_parents,
            output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()


def test_match_all_unassigned(tmp_path):
    """Every child fails to match any parent.

    match() should raise, not silently write an empty output file.
    """
    children_path = tmp_path / "children_far.parquet"
    parents_path = tmp_path / "parents_near.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[3]])  # fid 4, far from any parent
    _write_synthetic(parents_path, _PARENT_WKT)

    output_path = tmp_path / "out.parquet"
    with pytest.raises(RuntimeError, match="no group produced any output"):
        match(children_path, parents_path, output_path, overwrite=True)
