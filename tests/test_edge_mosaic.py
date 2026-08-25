"""Portability smoke tests: does mosaic() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on coverage violations, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import logging

import duckdb
import pytest
from click.testing import CliRunner

import topo_tools.core.edge_extend.attempt as attempt_module
from topo_tools.api.edge_mosaic import mosaic
from topo_tools.cli.main import cli

# All four children share one file, so one-file-one-parent applies: children
# 1+2 tile Parent A (0,0)-(3,3), giving that file's majority vote to A, so
# child 3 (Parent B (10,0)-(13,3) territory) and child 4 (unassignable
# anywhere) both end up dropped as unassigned, not routed to their own best
# parent individually.
_CHILD_WKT = [
    (1, "POLYGON((-5 -5, 1.5 -5, 1.5 5, -5 5, -5 -5))"),
    (2, "POLYGON((1.5 -5, 8 -5, 8 5, 1.5 5, 1.5 -5))"),
    (3, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))"),
    (4, "POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))"),
]
_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))"),
]

_PARENT_A_AREA = 9.0

_STEPS = ["inputs", "assign", "clip", "stitch", "outputs"]


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
    """Write a small synthetic already-extended child-layer GeoParquet."""
    path = tmp_path / "children.parquet"
    _write_synthetic(path, _CHILD_WKT)
    return path


@pytest.fixture
def synthetic_parents(tmp_path):
    """Write a small synthetic parent/clip-layer GeoParquet."""
    path = tmp_path / "parents.parquet"
    _write_synthetic(path, _PARENT_WKT)
    return path


@pytest.fixture
def synthetic_children_split(tmp_path):
    """Write children 1 & 2 (the Parent A tiling pair) to separate files."""
    path_a = tmp_path / "child_a.parquet"
    path_b = tmp_path / "child_b.parquet"
    _write_synthetic(path_a, [_CHILD_WKT[0]])
    _write_synthetic(path_b, [_CHILD_WKT[1]])
    return [path_a, path_b]


# file_a tiles Parent A (0,0)-(3,3) at x=1.5, but child 2 also straddles into
# Parent B (10,0)-(13,3) with a bigger individual overlap there (area 6 vs 4.5),
# so its own plurality would pick B, but file_a's vote count (2 children touch
# A, 1 touches B) should still pick A.
_MAJORITY_CHILD_A = (1, "POLYGON((-5 -5, 1.5 -5, 1.5 5, -5 5, -5 -5))")
_MAJORITY_CHILD_STRADDLE = (2, "POLYGON((1.5 -5, 12 -5, 12 5, 1.5 5, 1.5 -5))")
_MAJORITY_CHILD_B_ONLY = (3, "POLYGON((8 -5, 20 -5, 20 20, 8 20, 8 -5))")


@pytest.fixture
def synthetic_children_file_majority(tmp_path):
    """file_a tiles Parent A, one child straddling B; file_b feeds Parent B alone."""
    path_a = tmp_path / "file_a.parquet"
    path_b = tmp_path / "file_b.parquet"
    _write_synthetic(path_a, [_MAJORITY_CHILD_A, _MAJORITY_CHILD_STRADDLE])
    _write_synthetic(path_b, [_MAJORITY_CHILD_B_ONLY])
    return [path_a, path_b]


def test_cli_help():
    result = CliRunner().invoke(cli, ["edge-mosaic", "--help"])
    assert result.exit_code == 0
    assert "Fit an already-extended children layer" in result.output
    assert "Examples:" in result.output


def test_mosaic_full_run(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "out.parquet"
    mosaic(synthetic_children, synthetic_parents, output_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT id FROM '{output_path}' ORDER BY id"
            ).fetchall()
        ]
    assert ids == [1, 2]


def test_mosaic_drops_unassigned_and_warns(synthetic_parents, tmp_path, caplog):
    """A whole file with no parent overlap at all is dropped and warned about."""
    file_far = tmp_path / "file_far.parquet"
    file_a = tmp_path / "file_a.parquet"
    _write_synthetic(file_far, [_CHILD_WKT[3]])  # sole child, far from any parent
    _write_synthetic(file_a, [_CHILD_WKT[0], _CHILD_WKT[1]])  # tiles Parent A

    output_path = tmp_path / "out.parquet"
    with caplog.at_level(logging.WARNING):
        mosaic([file_far, file_a], synthetic_parents, output_path, overwrite=True)

    assert any("dropping 1 child fid(s)" in r.message for r in caplog.records)


def test_mosaic_issues_file_default_path(
    synthetic_children, synthetic_parents, tmp_path
):
    output_path = tmp_path / "out.parquet"
    mosaic(synthetic_children, synthetic_parents, output_path, overwrite=True)

    expected_issues_path = output_path.with_stem(output_path.stem + "_issues")
    assert expected_issues_path.exists()


def test_mosaic_issues_file_records_clip_empty_child(
    synthetic_children, synthetic_parents, tmp_path
):
    """Children 3/4 are forced onto Parent A, then dropped as clip-empty."""
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    mosaic(
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

    expected_clip_empty_fids = {3, 4}
    assert len(rows) == len(expected_clip_empty_fids)
    by_fid = {dict(zip(cols, row, strict=True))["unit_a"]: row for row in rows}
    assert set(by_fid) == expected_clip_empty_fids
    for row in rows:
        parsed = dict(zip(cols, row, strict=True))
        assert parsed["kind"] == "clip-empty"
        assert parsed["parent_fid"] == 1
        assert parsed["reason"] is not None
        assert parsed["geometry"] is not None


def test_mosaic_issues_file_absent_when_nothing_dropped(tmp_path):
    """Parent B's single-child case succeeds cleanly, so no issues file is written."""
    children_path = tmp_path / "children_single.parquet"
    parents_path = tmp_path / "parents_single.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[2]])  # fid 3 only
    _write_synthetic(parents_path, [_PARENT_WKT[1]])  # Parent B only

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    mosaic(children_path, parents_path, output_path, issues_path, overwrite=True)

    assert not issues_path.exists()


# A parent with a real interior hole (e.g. an enclosed country like Lesotho
# inside South Africa): two already-extended children exactly tile the outer
# square, so the hole survives clipping without any gap the children
# themselves created.
_ENCLAVE_PARENT_WKT = [
    (1, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4))"),
]
_ENCLAVE_CHILD_WKT = [
    (1, "POLYGON((0 0, 5 0, 5 10, 0 10, 0 0))"),
    (2, "POLYGON((5 0, 10 0, 10 10, 5 10, 5 0))"),
]


def test_mosaic_tolerates_parent_layer_enclave(tmp_path):
    """A real hole in the parent's own shape must not raise, only be reported."""
    children_path = tmp_path / "children_enclave.parquet"
    parents_path = tmp_path / "parents_enclave.parquet"
    _write_synthetic(children_path, _ENCLAVE_CHILD_WKT)
    _write_synthetic(parents_path, _ENCLAVE_PARENT_WKT)

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    mosaic(children_path, parents_path, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        gap_rows = conn.execute(
            f"SELECT max_width_m FROM '{issues_path}' WHERE kind = 'gap'"
        ).fetchall()
    assert len(gap_rows) == 1
    assert gap_rows[0][0] > 0


def test_mosaic_clip_bounds_output_to_parent(
    synthetic_children, synthetic_parents, tmp_path
):
    """Oversized already-extended children clip down to the parent's true extent."""
    output_path = tmp_path / "out.parquet"
    mosaic(synthetic_children, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        area = conn.execute(f"""--sql
            SELECT ST_Area(ST_Union_Agg(geometry))
            FROM '{output_path}' WHERE id IN (1, 2)
        """).fetchone()[0]
    assert area == pytest.approx(_PARENT_A_AREA, abs=1e-6)


def test_mosaic_all_unassigned(tmp_path):
    """All children unassigned: mosaic() must raise, not write an empty output."""
    children_path = tmp_path / "children_far.parquet"
    parents_path = tmp_path / "parents_near.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[3]])  # fid 4, far from any parent
    _write_synthetic(parents_path, _PARENT_WKT)

    output_path = tmp_path / "out.parquet"
    with pytest.raises(RuntimeError, match="no child was assigned to any parent"):
        mosaic(children_path, parents_path, output_path, overwrite=True)


def test_mosaic_default_output_path(synthetic_children, synthetic_parents):
    mosaic(synthetic_children, synthetic_parents, overwrite=True)

    expected = synthetic_children.with_stem(synthetic_children.stem + "_mosaicked")
    assert expected.exists()


def test_cli_positional_args(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-mosaic",
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
            "edge-mosaic",
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
    result = CliRunner().invoke(cli, ["edge-mosaic", str(synthetic_children)])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_cli_error_on_existing_output(synthetic_children, synthetic_parents, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        [
            "edge-mosaic",
            str(synthetic_children),
            str(synthetic_parents),
            str(output_path),
            "--overwrite=false",
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "output already exists" in result.output


def test_mosaic_steps(synthetic_children, synthetic_parents, tmp_path):
    """Each pipeline stage runs standalone, reusing one tmp_dir's DuckDB file."""
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        mosaic(
            synthetic_children,
            synthetic_parents,
            output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()


def test_mosaic_never_invokes_extend_pipeline(
    synthetic_children, synthetic_parents, tmp_path, monkeypatch
):
    """Regression guard: mosaic must never re-run extend's Voronoi pipeline."""

    def _boom(*_args, **_kwargs):
        msg = "mosaic must not invoke extend's Voronoi pipeline"
        raise AssertionError(msg)

    monkeypatch.setattr(attempt_module, "main", _boom)

    output_path = tmp_path / "out.parquet"
    mosaic(synthetic_children, synthetic_parents, output_path, overwrite=True)
    assert output_path.exists()


def test_mosaic_multi_file_api(synthetic_children_split, synthetic_parents, tmp_path):
    output_path = tmp_path / "out.parquet"
    mosaic(synthetic_children_split, synthetic_parents, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, source_file FROM '{output_path}' ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == [1, 2]
    assert rows[0][1] == str(synthetic_children_split[0])
    assert rows[1][1] == str(synthetic_children_split[1])


def test_mosaic_multi_file_requires_output_path(
    synthetic_children_split, synthetic_parents
):
    with pytest.raises(ValueError, match="output_path is required"):
        mosaic(synthetic_children_split, synthetic_parents)


def test_mosaic_single_path_still_optional_output(
    synthetic_children, synthetic_parents
):
    """Contrast case: a single (non-list) path still defaults output_path."""
    mosaic(synthetic_children, synthetic_parents, overwrite=True)
    assert synthetic_children.with_stem(synthetic_children.stem + "_mosaicked").exists()


def test_cli_glob_expansion(
    synthetic_children_split,  # noqa: ARG001 (write side effect is the point)
    synthetic_parents,
    tmp_path,
):
    output_path = tmp_path / "out.parquet"
    pattern = str(tmp_path / "child_*.parquet")
    result = CliRunner().invoke(
        cli,
        ["edge-mosaic", pattern, str(synthetic_parents), str(output_path)],
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


def test_mosaic_file_majority_vote_overrides_child_plurality(
    synthetic_children_file_majority, synthetic_parents, tmp_path
):
    """A child whose plurality favors the wrong parent must follow its file majority."""
    output_path = tmp_path / "out.parquet"
    mosaic(
        synthetic_children_file_majority,
        synthetic_parents,
        output_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, ST_Area(geometry) FROM '{output_path}' ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    straddler_area = dict(rows)[2]
    assert straddler_area == pytest.approx(4.5, abs=1e-6)


def test_cli_extra_input_flag_combines_with_glob(
    synthetic_children_file_majority, synthetic_parents, tmp_path
):
    """A glob-matched file plus a --input-flagged file both feed one combined run."""
    file_a, file_b = synthetic_children_file_majority
    output_path = tmp_path / "out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-mosaic",
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
    assert ids == [1, 2, 3]


def test_cli_glob_no_matches(synthetic_parents, tmp_path):
    pattern = str(tmp_path / "nomatch_*.parquet")
    result = CliRunner().invoke(
        cli,
        ["edge-mosaic", pattern, str(synthetic_parents), str(tmp_path / "out.parquet")],
    )
    assert result.exit_code != 0
    assert "no files matched" in result.output


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
    """rows: list of (pid, wkt, pcode); no `id` column to collide with a child's."""
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


def test_match_overrides_spatial_and_reports_mismatch(tmp_path):
    """A child's own file mostly overlaps parent A, but its code says B."""
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
        [(1, "POLYGON((1 0, 10.5 0, 10.5 1, 1 1, 1 0))", "P2")],
    )

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    mosaic(
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
    # Clipped to parent B's sliver (x:10-10.5), not parent A's larger x:1-3.
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
    mosaic(
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


def test_cli_match_help():
    result = CliRunner().invoke(cli, ["edge-mosaic", "--help"])
    assert result.exit_code == 0
    assert "--match-column" in result.output
    assert "--parent-match-column" in result.output
    assert "--child-match-column" in result.output


def test_mosaic_merge_columns_populates_output(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")])
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0]])

    output_path = tmp_path / "out.parquet"
    mosaic(
        children_path,
        parents_path,
        output_path,
        merge_columns=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        pcode = conn.execute(f"SELECT pcode FROM '{output_path}'").fetchone()[0]
    assert pcode == "P1"


def test_mosaic_merge_bare_carries_every_parent_column(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path, [(1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1")]
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, [_CHILD_WKT[0]])

    output_path = tmp_path / "out.parquet"
    mosaic(children_path, parents_path, output_path, merge_columns=True, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row = conn.execute(f"SELECT id, pid, pcode FROM '{output_path}'").fetchone()
    assert row == (1, 1, "P1")


def test_mosaic_gap_fill_keeps_unmatched_parent(tmp_path):
    """Parent B (fid 2) gets zero matched children, so it carries through unclipped."""
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
    mosaic(
        children_path,
        parents_path,
        output_path,
        issues_path,
        merge_columns=["pcode"],
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


def test_mosaic_gap_fill_still_reports_clip_empty_children(tmp_path):
    """Gap-fill rescues Parent B; children 3/4 still clip-empty against Parent A."""
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
    mosaic(
        children_path,
        parents_path,
        output_path,
        issues_path,
        merge_columns=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        clip_empty_fids = {
            row[0]
            for row in conn.execute(
                f"SELECT unit_a FROM '{issues_path}' WHERE kind = 'clip-empty'"
            ).fetchall()
        }
    assert clip_empty_fids == {3, 4}


def test_mosaic_gap_fill_merged_columns_populated(tmp_path):
    """A gap-filled parent's carried columns hold its own real value, not NULL."""
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
    mosaic(
        children_path,
        parents_path,
        output_path,
        merge_columns=["pcode"],
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        pcode = conn.execute(
            f"SELECT pcode FROM '{output_path}' WHERE parent_fid = 2"
        ).fetchone()[0]
    assert pcode == "P2"


def test_cli_merge_gap_fill(tmp_path):
    parents_path = tmp_path / "parents.parquet"
    _write_parent_pcode_only(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
        ],
    )
    children_path = tmp_path / "children.parquet"
    _write_synthetic(children_path, _CHILD_WKT)
    output_path = tmp_path / "out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-mosaic",
            str(children_path),
            str(parents_path),
            str(output_path),
            "--merge",
        ],
    )
    assert result.exit_code == 0, result.output
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        parent_fids = {
            row[0]
            for row in conn.execute(
                f"SELECT parent_fid FROM '{output_path}'"
            ).fetchall()
        }
    gap_filled_parent_fid = 2
    assert gap_filled_parent_fid in parent_fids


def test_cli_merge_help():
    result = CliRunner().invoke(cli, ["edge-mosaic", "--help"])
    assert result.exit_code == 0
    assert "--merge" in result.output


def test_mosaic_multi_file_zero_overlap_file_does_not_abort_batch(tmp_path):
    """A zero-overlap file in a 3+ file default-drop batch must not abort the run."""
    parents_path = tmp_path / "parents.parquet"
    _write_synthetic(parents_path, _PARENT_WKT)
    file_a = tmp_path / "file_a.parquet"
    file_b = tmp_path / "file_b.parquet"
    file_c = tmp_path / "file_c.parquet"
    _write_synthetic(file_a, [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))")])
    _write_synthetic(
        file_b, [(2, "POLYGON((10.5 0.5, 11 0.5, 11 1, 10.5 1, 10.5 0.5))")]
    )
    _write_synthetic(
        file_c, [(3, "POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))")]
    )

    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    mosaic(
        [file_a, file_b, file_c], parents_path, output_path, issues_path, overwrite=True
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
    assert ids == [1, 2]
    assert kinds == ["unassigned"]


def test_mosaic_multi_file_code_join_fid_stays_unique(tmp_path):
    """Per-file fid_offset keeps child_fid globally unique across a 3+ file batch."""
    parents_path = tmp_path / "parents.parquet"
    _write_with_code(
        parents_path,
        [
            (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
            (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
            (3, "POLYGON((20 0, 23 0, 23 3, 20 3, 20 0))", "P3"),
        ],
    )
    file_a = tmp_path / "file_a.parquet"
    file_b = tmp_path / "file_b.parquet"
    file_c = tmp_path / "file_c.parquet"
    _write_with_code(
        file_a, [(1, "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))", "P1")]
    )
    _write_with_code(
        file_b, [(2, "POLYGON((10.5 0.5, 11 0.5, 11 1, 10.5 1, 10.5 0.5))", "P2")]
    )
    _write_with_code(
        file_c, [(3, "POLYGON((20.5 0.5, 21 0.5, 21 1, 20.5 1, 20.5 0.5))", "P3")]
    )

    output_path = tmp_path / "out.parquet"
    mosaic(
        [file_a, file_b, file_c],
        parents_path,
        output_path,
        match_column="pcode",
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT id, source_file FROM '{output_path}' ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert rows[0][1] == str(file_a)
    assert rows[1][1] == str(file_b)
    assert rows[2][1] == str(file_c)


def test_mosaic_multi_file_step_rejected(
    synthetic_children_split, synthetic_parents, tmp_path
):
    with pytest.raises(ValueError, match="step is not supported"):
        mosaic(
            synthetic_children_split,
            synthetic_parents,
            tmp_path / "out.parquet",
            step="assign",
            overwrite=True,
        )
