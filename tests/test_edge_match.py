"""Portability smoke tests: does match() run to completion on this machine.

Not a correctness suite: outputs.main already raises RuntimeError on
coverage violations, so a clean run is already vetted by the pipeline itself.
"""

import logging

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.edge_match import match
from topo_tools.cli.main import cli
from topo_tools.core.constants import SNAP_TOLERANCE
from topo_tools.core.coverage import has_gaps
from topo_tools.core.edge_match import _01_inputs
from topo_tools.core.edge_match import _03_clip as match_clip
from topo_tools.core.edge_match._02_groups import _record_dropped_group

# Parent A contains children 1 & 2, Parent B contains only child 3, child 4
# is far from both; --multi-parent restores this per-child grouping.
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


def test_inputs_cleans_child_but_loads_parent_raw(tmp_path):
    """The child's sub-tolerance gap is closed; the same gap in the parent is not."""
    w = SNAP_TOLERANCE / 2
    wkt = [
        (1, f"POLYGON((0 0, 101 0, 101 50, {50 + w} 50, 50 50, 0 50, 0 0))"),
        (
            2,
            (
                f"POLYGON((0 {50 + w}, 50 {50 + w}, {50 + w} {50 + w}, "
                f"101 {50 + w}, 101 101, 0 101, 0 {50 + w}))"
            ),
        ),
        (3, f"POLYGON((0 50, 50 50, 50 {50 + w}, 0 {50 + w}, 0 50))"),
        (
            4,
            (
                f"POLYGON(({50 + w} 50, 101 50, 101 {50 + w}, "
                f"{50 + w} {50 + w}, {50 + w} 50))"
            ),
        ),
    ]
    path = tmp_path / "gapped.parquet"
    _write_synthetic(path, wkt)

    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        _01_inputs.main(conn, "t", path, path)
        assert not has_gaps(conn, "t_child_01", gap_maximum_width=0)
        assert has_gaps(conn, "t_parent_01", gap_maximum_width=0)


def test_cli_help():
    result = CliRunner().invoke(cli, ["edge-match", "--help"])
    assert result.exit_code == 0
    assert "Match one or more children layers to parents" in result.output
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
    """Default assign-one forces the whole file onto Parent A; child 3 clip-empties."""
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
    assert ids == [1, 2, 4]


def test_match_multi_parent_preserves_per_child_grouping(
    synthetic_children, synthetic_parents, tmp_path
):
    """--multi-parent restores the old per-child groups: 1&2, 3, and 4 dropped."""
    output_path = tmp_path / "out.parquet"
    match(
        synthetic_children,
        synthetic_parents,
        output_path,
        multi_parent=True,
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
    assert ids == [1, 2, 3]


def test_match_drops_unassigned_and_warns(
    synthetic_children, synthetic_parents, tmp_path, caplog
):
    """Only --multi-parent's per-child assign can leave a child with no winner."""
    output_path = tmp_path / "out.parquet"
    with caplog.at_level(logging.WARNING):
        match(
            synthetic_children,
            synthetic_parents,
            output_path,
            multi_parent=True,
            overwrite=True,
        )

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
    """--multi-parent's per-child assign leaves child 4 with no winner at all."""
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        synthetic_children,
        synthetic_parents,
        output_path,
        issues_path,
        multi_parent=True,
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


def test_match_default_issues_file_records_clip_empty_child(
    synthetic_children, synthetic_parents, tmp_path
):
    """Default assign-one forces child 3 onto Parent A; its clip comes back empty."""
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

    clip_empty_child_fid = 3
    winning_parent_fid = 1
    assert len(rows) == 1
    row = dict(zip(cols, rows[0], strict=True))
    assert row["kind"] == "clip-empty"
    assert row["unit_a"] == clip_empty_child_fid
    assert row["parent_fid"] == winning_parent_fid
    assert row["reason"] is not None


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


# A parent with a real interior hole (e.g. Lesotho inside South Africa);
# two children exactly tile the outer square, so no gap is self-inflicted.
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
                (1, 'children.parquet',
                    ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
                (2, 'children.parquet',
                    ST_GeomFromText('POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))'))
            ) AS v(fid, source_file, geom)
        """)
        conn.execute("""--sql
            CREATE TABLE t_02_assign AS
            SELECT * FROM (VALUES (1, 10), (2, 10)) AS v(child_fid, parent_fid)
        """)
        conn.execute("""--sql
            CREATE TABLE t_03b AS
            SELECT NULL::BIGINT AS child_fid, NULL::BIGINT AS parent_fid,
                   NULL::VARCHAR AS reason, NULL::VARCHAR AS source_file,
                   NULL::GEOMETRY AS geom
            WHERE FALSE
        """)

        _record_dropped_group(
            conn,
            "t",
            10,
            "boom: something failed",
            'SELECT child_fid FROM "t_02_assign" WHERE parent_fid = 10',
        )

        rows = conn.execute(
            "SELECT child_fid, parent_fid, reason FROM t_03b ORDER BY child_fid"
        ).fetchall()

    assert rows == [
        (1, 10, "boom: something failed"),
        (2, 10, "boom: something failed"),
    ]


def test_match_clip_step_aborts_on_bad_parent_fid(tmp_path):
    """A single bad parent_fid in the clip step aborts the whole run.

    clip's hard-fail-on-first-bad-parent_fid semantics apply uniformly to
    match too, not match's old per-group continue-past-failure behavior.
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


def _write_parent_pcode_only(path, rows):
    """rows: list of (pid, wkt, pcode); no 'id' column, avoids a merge collision."""
    values = ", ".join(
        f"({pid}, ST_GeomFromText('{wkt}'), '{code}')" for pid, wkt, code in rows
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"""--sql
            CREATE TABLE synth AS
            SELECT * FROM (VALUES {values}) AS t(pid, geom, pcode)
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
        merge=True,
        parent_include=["pcode"],
        multi_parent=True,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, pcode FROM '{output_path}' ORDER BY id"
        ).fetchall()
    assert rows == [(1, "P1"), (2, "P1"), (3, "P2")]


def test_cli_merge_help():
    result = CliRunner().invoke(cli, ["edge-match", "--help"])
    assert result.exit_code == 0
    assert "--merge" in result.output
    assert "--carry-column" not in result.output


def test_match_merge_bare_passthrough_keeps_orphan_and_carries_columns(tmp_path):
    """Bare --merge carries every parent column and keeps an orphan unclipped."""
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, _CHILD_WKT)  # fids 1-4; 4 is far, unmatched

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        issues_path,
        merge=True,
        multi_parent=True,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, pcode FROM '{output_path}' ORDER BY id"
        ).fetchall()
        kinds = [
            row[0]
            for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
        ]

    assert rows == [(1, "P1"), (2, "P1"), (3, "P2"), (4, None)]
    assert "passthrough" in kinds
    assert "unassigned" not in kinds


def test_match_no_merge_still_drops_orphan(tmp_path):
    """Without --merge, an orphan is dropped and reported unassigned, as before."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, _CHILD_WKT)

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        issues_path,
        multi_parent=True,
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
        kinds = [
            row[0]
            for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
        ]

    assert ids == [1, 2, 3]
    assert kinds == ["unassigned"]


def test_match_gap_fill_keeps_unmatched_parent(tmp_path):
    """Parent B gets zero matched children, so it carries through unclipped."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0], _CHILD_WKT[1]])

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        issues_path,
        merge=True,
        parent_include=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT parent_fid, pcode FROM '{output_path}' WHERE parent_fid = 2"
        ).fetchall()
        issue_rows = conn.execute(
            f"SELECT kind, parent_fid FROM '{issues_path}' WHERE kind = 'gap-fill'"
        ).fetchall()
    assert rows == [(2, "P2")]
    assert issue_rows == [("gap-fill", 2)]


def test_match_gap_fill_and_passthrough_together(tmp_path):
    """An unmatched parent and an unmatched child file can both appear in one run."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    file_a = tmp_path / "file_a.parquet"
    file_far = tmp_path / "file_far.parquet"
    _write_synthetic(file_a, [_CHILD_WKT[0]])  # matches Parent A only
    _write_synthetic(file_far, [_CHILD_WKT[3]])  # zero overlap with any parent

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        [file_a, file_far],
        parents_path,
        output_path,
        issues_path,
        merge=True,
        parent_include=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        kinds = {
            row[0]
            for row in conn.execute(f"SELECT kind FROM '{issues_path}'").fetchall()
        }
    assert "gap-fill" in kinds
    assert "passthrough" in kinds


def test_match_child_exclude_drops_named_child_column(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")]
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0]])

    output_path = tmp_path / "out.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        merge=True,
        child_exclude=["id"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            row[0] for row in conn.execute(f"DESCRIBE '{output_path}'").fetchall()
        }
    assert "id" not in columns
    assert "pcode" in columns


def test_match_narrowing_flag_without_merge_raises(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")]
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0]])

    with pytest.raises(ValueError, match="require merge"):
        match(
            children_path,
            parents_path,
            tmp_path / "out.parquet",
            parent_include=["pcode"],
            overwrite=True,
        )


def test_match_prefer_mutually_exclusive_with_narrowing_flags(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")]
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0]])

    with pytest.raises(ValueError, match="mutually exclusive"):
        match(
            children_path,
            parents_path,
            tmp_path / "out.parquet",
            merge=True,
            prefer="parent",
            parent_include=["pcode"],
            overwrite=True,
        )


def test_match_prefer_parent_resolves_real_collision(tmp_path):
    """id/geom/pcode all overlap between the two layers; pcode is the real collision."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")])
    children_path = tmp_path / "children.parquet"
    _write_with_code(
        children_path,
        [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))", "CHILDVAL")],
    )

    output_path = tmp_path / "out.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        merge=True,
        prefer="parent",
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        pcode = conn.execute(f"SELECT pcode FROM '{output_path}'").fetchone()[0]
    assert pcode == "P1"


def test_match_prefer_child_resolves_real_collision(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")])
    children_path = tmp_path / "children.parquet"
    _write_with_code(
        children_path,
        [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))", "CHILDVAL")],
    )

    output_path = tmp_path / "out.parquet"
    match(
        children_path,
        parents_path,
        output_path,
        merge=True,
        prefer="child",
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        pcode = conn.execute(f"SELECT pcode FROM '{output_path}'").fetchone()[0]
    assert pcode == "CHILDVAL"


@pytest.fixture
def synthetic_children_split(tmp_path):
    """Write children 1 & 2 (the Parent A pair) to separate files."""
    path_a = tmp_path / "child_a.parquet"
    path_b = tmp_path / "child_b.parquet"
    _write_synthetic(path_a, [_CHILD_WKT[0]])
    _write_synthetic(path_b, [_CHILD_WKT[1]])
    return [path_a, path_b]


@pytest.fixture
def synthetic_children_split_with_orphan(tmp_path):
    """Children 1 & 2 (Parent A pair) plus an unmatched child, each its own file."""
    path_a = tmp_path / "child_a.parquet"
    path_b = tmp_path / "child_b.parquet"
    path_c = tmp_path / "child_c.parquet"
    _write_synthetic(path_a, [_CHILD_WKT[0]])
    _write_synthetic(path_b, [_CHILD_WKT[1]])
    _write_synthetic(path_c, [_CHILD_WKT[3]])
    return [path_a, path_b, path_c]


def test_match_multi_file_api(synthetic_children_split, synthetic_parents, tmp_path):
    """Children from different files landing on the same parent extend together."""
    output_path = tmp_path / "out.parquet"
    match(synthetic_children_split, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            row[0] for row in conn.execute(f"DESCRIBE '{output_path}'").fetchall()
        }
        rows = conn.execute(f"SELECT id FROM '{output_path}' ORDER BY id").fetchall()
    assert "source_file" not in columns
    assert [r[0] for r in rows] == [1, 2]


def test_match_multi_file_rejects_multi_parent(
    synthetic_children_split, synthetic_parents, tmp_path
):
    with pytest.raises(ValueError, match="multi_parent is not supported"):
        match(
            synthetic_children_split,
            synthetic_parents,
            tmp_path / "out.parquet",
            multi_parent=True,
            overwrite=True,
        )


def test_match_multi_file_rejects_step(
    synthetic_children_split, synthetic_parents, tmp_path
):
    with pytest.raises(ValueError, match="step is not supported"):
        match(
            synthetic_children_split,
            synthetic_parents,
            tmp_path / "out.parquet",
            step="assign",
            overwrite=True,
        )


def test_match_multi_file_requires_output_path(
    synthetic_children_split, synthetic_parents
):
    with pytest.raises(ValueError, match="output_path is required"):
        match(synthetic_children_split, synthetic_parents)


def test_match_multi_file_source_file_populated_in_issues(
    synthetic_children_split_with_orphan, synthetic_parents, tmp_path
):
    """Issues rows carry a parent-dir/filename source_file, not the full path."""
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    match(
        synthetic_children_split_with_orphan,
        synthetic_parents,
        output_path,
        issues_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT source_file FROM '{issues_path}' WHERE kind = 'unassigned'"
        ).fetchall()
    orphan_path = synthetic_children_split_with_orphan[2]
    assert len(rows) == 1
    assert rows[0][0] == "/".join(orphan_path.parts[-2:])


def test_cli_edge_match_glob_expansion(
    synthetic_children_split,  # noqa: ARG001 (write side effect is the point)
    synthetic_parents,
    tmp_path,
):
    output_path = tmp_path / "out.parquet"
    pattern = str(tmp_path / "child_*.parquet")
    result = CliRunner().invoke(
        cli,
        ["edge-match", pattern, str(synthetic_parents), str(output_path)],
    )
    assert result.exit_code == 0, result.output

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT id FROM '{output_path}' ORDER BY id"
            ).fetchall()
        ]
    assert ids == [1, 2]


def test_cli_edge_match_extra_input_flag_combines_with_glob(
    synthetic_children_split, synthetic_parents, tmp_path
):
    """A glob-matched file plus a --input-flagged file both feed one combined run."""
    file_a, file_b = synthetic_children_split
    output_path = tmp_path / "out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-match",
            str(file_a),
            str(synthetic_parents),
            str(output_path),
            "--input",
            str(file_b),
        ],
    )
    assert result.exit_code == 0, result.output

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT id FROM '{output_path}' ORDER BY id"
            ).fetchall()
        ]
    assert ids == [1, 2]


def test_cli_edge_match_glob_no_matches(synthetic_parents, tmp_path):
    pattern = str(tmp_path / "nomatch_*.parquet")
    result = CliRunner().invoke(
        cli,
        ["edge-match", pattern, str(synthetic_parents), str(tmp_path / "out.parquet")],
    )
    assert result.exit_code != 0
    assert "no files matched" in result.output
