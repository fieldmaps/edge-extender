"""Portability smoke tests: does match() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on coverage violations, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import logging

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.edge_match import match
from topo_tools.cli.main import cli
from topo_tools.core.edge_match import _03_clip as match_clip
from topo_tools.core.edge_match._02_groups import _record_dropped_group

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
    result = CliRunner().invoke(cli, ["edge-match", "--help"])
    assert result.exit_code == 0
    assert "Match children to parents" in result.output
    assert "Examples:" in result.output
    assert "--match-column" in result.output
    assert "--parent-match-column" in result.output
    assert "--child-match-column" in result.output


def test_match_mutually_exclusive_with_pair(
    synthetic_children, synthetic_parents, tmp_path
):
    with pytest.raises(ValueError, match="mutually exclusive"):
        match(
            synthetic_children,
            synthetic_parents,
            tmp_path / "out.parquet",
            match_column="pcode",
            parent_match_column="pcode",
        )


def test_match_agrees_with_spatial_is_a_noop(
    synthetic_children, synthetic_parents, tmp_path
):
    """Code agreeing with spatial everywhere must reproduce the default run exactly."""
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        parent_by_child = dict(
            conn.execute(f"""--sql
                SELECT c.id, p.id FROM '{synthetic_children}' c, '{synthetic_parents}' p
                WHERE ST_Intersects(c.geom, p.geom)
            """).fetchall()
        )
    children_with_code = tmp_path / "children_coded.parquet"
    parents_with_code = tmp_path / "parents_coded.parquet"
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        conn.execute(f"""--sql
            COPY (SELECT *, CAST(id AS VARCHAR) AS pcode FROM '{synthetic_parents}')
            TO '{parents_with_code}'
        """)
        rows = ", ".join(
            f"({fid}, '{parent_by_child.get(fid, 0)}')" for fid in parent_by_child
        )
        conn.execute(f"""--sql
            COPY (
                SELECT c.*, m.pcode FROM '{synthetic_children}' c
                JOIN (SELECT * FROM (VALUES {rows}) AS v(id, pcode)) m ON m.id = c.id
            ) TO '{children_with_code}'
        """)

    match(
        children_with_code,
        parents_with_code,
        output_path,
        issues_path,
        match_column="pcode",
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT id FROM '{output_path}' ORDER BY id"
            ).fetchall()
        ]
        kinds = (
            [
                row[0]
                for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
            ]
            if issues_path.exists()
            else []
        )
    assert ids == [1, 2, 3]
    assert "code-mismatch" not in kinds


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
    assert row["unit_a"] == unassigned_child_fid
    assert row["parent_fid"] is None
    assert row["reason"] is None
    assert row["geometry"] is not None


def test_match_issues_file_absent_when_nothing_dropped(tmp_path):
    """Parent B's single-child group succeeds cleanly, so no issues file is written."""
    children_path = tmp_path / "children_single.parquet"
    parents_path = tmp_path / "parents_single.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[2]])  # fid 3 only
    _write_synthetic(parents_path, [_PARENT_WKT[1]])  # Parent B only

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(children_path, parents_path, output_path, issues_path, overwrite=True)

    assert not issues_path.exists()


# A parent with a real interior hole (e.g. an enclosed country like Lesotho
# inside South Africa): two children exactly tile the outer square, so the
# hole survives clipping without any gap the children themselves created.
_ENCLAVE_PARENT_WKT = [
    (1, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4))"),
]
_ENCLAVE_CHILD_WKT = [
    (1, "POLYGON((0 0, 5 0, 5 10, 0 10, 0 0))"),
    (2, "POLYGON((5 0, 10 0, 10 10, 5 10, 5 0))"),
]


def test_match_tolerates_parent_layer_enclave(tmp_path):
    """A real hole in the parent's own shape must not raise, only be reported."""
    children_path = tmp_path / "children_enclave.parquet"
    parents_path = tmp_path / "parents_enclave.parquet"
    _write_synthetic(children_path, _ENCLAVE_CHILD_WKT)
    _write_synthetic(parents_path, _ENCLAVE_PARENT_WKT)

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(children_path, parents_path, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        gap_rows = conn.execute(
            f"SELECT max_width_m FROM '{issues_path}' WHERE kind = 'gap'"
        ).fetchall()
    assert len(gap_rows) == 1
    assert gap_rows[0][0] > 0


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
        [
            "edge-match",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_issues_file_option(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    issues_path = tmp_path / "cli_issues.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-match",
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
    result = CliRunner().invoke(cli, ["edge-match", str(synthetic_children)])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_cli_clean_error_on_existing_output(
    synthetic_children, synthetic_parents, tmp_path
):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        [
            "edge-match",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
            "--overwrite=false",
        ],
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


def test_match_carry_columns_survives_group_subprocess(tmp_path):
    """A carried parent column must survive the per-group extend/merge round-trip."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, _CHILD_WKT[:3])  # fids 1, 2, 3, all matched

    output_path = tmp_path / "out.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        carry_columns=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, pcode FROM '{output_path}' ORDER BY id"
        ).fetchall()
    assert rows == [(1, "P1"), (2, "P1"), (3, "P2")]


def test_cli_carry_column_help():
    result = CliRunner().invoke(cli, ["edge-match", "--help"])
    assert result.exit_code == 0
    assert "--carry-column" in result.output
