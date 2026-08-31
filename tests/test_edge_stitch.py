"""Portability smoke tests: does stitch() run to completion on this machine.

Not a correctness suite: outputs.main already raises RuntimeError on
coverage violations, so a clean run is already vetted by the pipeline itself.
"""

from pathlib import Path

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.edge_stitch import stitch
from topo_tools.cli.main import cli
from topo_tools.core.coverage import has_invalid_edges
from topo_tools.core.schema_map._target_schema import DEFAULT_TARGET_SCHEMA_PATH

_STEPS = ["inputs", "clean", "outputs"]
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_LEVEL_1, _LEVEL_2 = 1, 2


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


@pytest.fixture
def tiny_gap_split(tmp_path):
    """Build the same tiny-gap frame as tiny_gap_input, split across two files."""
    rows = _frame_wkt(1e-9)
    path_a = tmp_path / "part_a.parquet"
    path_b = tmp_path / "part_b.parquet"
    _write_synthetic(path_a, rows[:2])
    _write_synthetic(path_b, rows[2:])
    return [path_a, path_b]


def test_cli_help():
    result = CliRunner().invoke(cli, ["edge-stitch", "--help"])
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


def test_stitch_drops_preexisting_source_file_column(tmp_path):
    """A source_file column already on the input must not survive into the output."""
    path = tmp_path / "tagged.parquet"
    values = ", ".join(
        f"({fid}, 'orig.parquet', ST_GeomFromText('{wkt}'))"
        for fid, wkt in _frame_wkt(1e-9)
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) "
            "AS t(id, source_file, geom)"
        )
        conn.execute(f"COPY synth TO '{path}'")

    output_path = tmp_path / "out.parquet"
    stitch(path, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            row[0] for row in conn.execute(f"DESCRIBE '{output_path}'").fetchall()
        }
    assert "source_file" not in columns


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
    result = CliRunner().invoke(
        cli, ["edge-stitch", str(tiny_gap_input), str(output_path)]
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_issues_file_option(large_gap_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    issues_path = tmp_path / "cli_issues.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "edge-stitch",
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
    result = CliRunner().invoke(
        cli, ["edge-stitch", str(tiny_gap_input), str(output_path), "--overwrite=false"]
    )
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


def test_stitch_multi_file_api(tiny_gap_split, tmp_path):
    output_path = tmp_path / "out.parquet"
    issues_path = tmp_path / "issues.parquet"
    stitch(tiny_gap_split, output_path, issues_path, overwrite=True)

    assert output_path.exists()
    assert not issues_path.exists()
    expected_row_count = 4
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count


def test_multi_file_column_order_is_deterministic_regardless_of_input_order(tmp_path):
    """UNION ALL BY NAME must not let caller-supplied file order pick the schema."""
    tiles = _frame_wkt(1e-9)

    deep_path = tmp_path / "deep.parquet"
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"""--sql
            CREATE TABLE deep AS SELECT * FROM (VALUES
                (1, 'A1', 'B1', 'C1', ST_GeomFromText('{tiles[0][1]}')),
                (2, 'A1', 'B1', 'C1', ST_GeomFromText('{tiles[1][1]}'))
            ) AS t(id, adm1_name, adm2_name, adm3_name, geom)
        """)
        conn.execute(f"COPY deep TO '{deep_path}'")

    shallow_path = tmp_path / "shallow.parquet"
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"""--sql
            CREATE TABLE shallow AS SELECT * FROM (VALUES
                (3, 'B2', ST_GeomFromText('{tiles[2][1]}')),
                (4, 'B2', ST_GeomFromText('{tiles[3][1]}'))
            ) AS t(id, adm2_name, geom)
        """)
        conn.execute(f"COPY shallow TO '{shallow_path}'")

    def _columns(paths, tag):
        output_path = tmp_path / f"out_{tag}.parquet"
        issues_path = tmp_path / f"issues_{tag}.parquet"
        stitch(list(paths), output_path, issues_path, overwrite=True)
        with duckdb.connect() as conn:
            conn.execute("LOAD spatial")
            return [
                row[0] for row in conn.execute(f"DESCRIBE '{output_path}'").fetchall()
            ]

    forward = _columns([deep_path, shallow_path], "forward")
    reverse = _columns([shallow_path, deep_path], "reverse")
    assert forward == reverse
    assert "adm1_name" in forward
    assert "adm3_name" in forward


def test_coincident_boundary_fixture_is_invalid_at_default_tolerance():
    """Guards the fixture itself: it must still repro INVALID_EDGES pre-fix."""
    path = _FIXTURES_DIR / "edge_stitch_coincident_boundary.parquet"
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(f"CREATE TABLE fixture AS SELECT * FROM '{path}'")
        assert has_invalid_edges(conn, "fixture")


def test_stitch_resolves_coincident_boundary_drift(tmp_path):
    """Two real adjacent units whose shared border coincides with the clip boundary."""
    path = _FIXTURES_DIR / "edge_stitch_coincident_boundary.parquet"
    output_path = tmp_path / "out.parquet"
    stitch(path, output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE out AS SELECT * EXCLUDE (geometry), geometry AS geom "
            f"FROM '{output_path}'"
        )
        assert not has_invalid_edges(conn, "out")


def test_stitch_multi_file_requires_output_path(tiny_gap_split):
    with pytest.raises(ValueError, match="output_path is required"):
        stitch(tiny_gap_split)


def test_cli_glob_expansion(
    tiny_gap_split,  # noqa: ARG001 (write side effect is the point)
    tmp_path,
):
    output_path = tmp_path / "out.parquet"
    pattern = str(tmp_path / "part_*.parquet")
    result = CliRunner().invoke(cli, ["edge-stitch", pattern, str(output_path)])
    assert result.exit_code == 0, result.output

    expected_row_count = 4
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count


def test_cli_extra_input_flag_combines_with_glob(tiny_gap_split, tmp_path):
    """One positional file + a --input-flagged file both feed one combined run."""
    file_a, file_b = tiny_gap_split
    output_path = tmp_path / "out.parquet"
    result = CliRunner().invoke(
        cli, ["edge-stitch", str(file_a), str(output_path), "--input", str(file_b)]
    )
    assert result.exit_code == 0, result.output

    expected_row_count = 4
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count


def test_cli_glob_no_matches(tmp_path):
    pattern = str(tmp_path / "nomatch_*.parquet")
    result = CliRunner().invoke(
        cli, ["edge-stitch", pattern, str(tmp_path / "out.parquet")]
    )
    assert result.exit_code != 0
    assert "no files matched" in result.output


def _write_admin_synthetic(path, rows: list[dict]) -> None:
    cols = [k for k in rows[0] if k != "wkt"]
    col_list = ", ".join([*cols, "geom"])
    values = ", ".join(
        "("
        + ", ".join(
            "NULL"
            if r[c] is None
            else f"'{r[c]}'"
            if isinstance(r[c], str)
            else str(r[c])
            for c in cols
        )
        + f", ST_GeomFromText('{r['wkt']}'))"
        for r in rows
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t({col_list})"
        )
        conn.execute(f"COPY synth TO '{path}'")


_ADMIN_ROWS = [
    {
        "adm1_code": "AA",
        "adm1_name": "Country A",
        "adm2_code": "AA01",
        "adm2_name": "Prov1",
        "wkt": _frame_wkt(1e-9)[0][1],
    },
    {
        "adm1_code": "AA",
        "adm1_name": "Country A",
        "adm2_code": "AA02",
        "adm2_name": "Prov2",
        "wkt": _frame_wkt(1e-9)[1][1],
    },
    {
        "adm1_code": "BB",
        "adm1_name": "Country B",
        "adm2_code": None,
        "adm2_name": None,
        "wkt": _frame_wkt(1e-9)[2][1],
    },
    {
        "adm1_code": "BB",
        "adm1_name": "Country B",
        "adm2_code": None,
        "adm2_name": None,
        "wkt": _frame_wkt(1e-9)[3][1],
    },
]


@pytest.fixture
def admin_input(tmp_path):
    path = tmp_path / "admin.parquet"
    _write_admin_synthetic(path, _ADMIN_ROWS)
    return path


def _columns_and_rows(path):
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        cols = [row[0] for row in conn.execute(f"DESCRIBE '{path}'").fetchall()]
        rows = conn.execute(
            f"SELECT * FROM '{path}' ORDER BY adm1_code, adm2_code"
        ).fetchall()
    return cols, rows


def test_fill_schema_off_by_default_leaves_output_unchanged(admin_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    stitch(admin_input, output_path, overwrite=True)
    cols, _ = _columns_and_rows(output_path)
    assert "adm_lvl" not in cols


def test_fill_schema_stamps_depth_and_fills(admin_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    stitch(admin_input, output_path, overwrite=True, fill_schema=True)
    cols, rows = _columns_and_rows(output_path)
    assert "adm_lvl" in cols
    lvl = cols.index("adm_lvl")
    name2 = cols.index("adm2_name")

    by_code = {
        (r[cols.index("adm1_code")], r[cols.index("adm2_code")]): r for r in rows
    }
    assert by_code[("AA", "AA01")][lvl] == _LEVEL_2
    assert by_code[("AA", "AA02")][lvl] == _LEVEL_2
    for r in rows:
        if r[cols.index("adm1_code")] == "BB":
            assert r[lvl] == _LEVEL_1
            assert r[name2] == "Country B"


def test_cli_fill_schema_flag(admin_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    result = CliRunner().invoke(
        cli, ["edge-stitch", str(admin_input), str(output_path), "--fill-schema"]
    )
    assert result.exit_code == 0, result.output
    cols, _ = _columns_and_rows(output_path)
    assert "adm_lvl" in cols


def test_fill_schema_without_admin_columns_raises(tiny_gap_input, tmp_path):
    with pytest.raises(ValueError, match=r"no .*level column found"):
        stitch(
            tiny_gap_input,
            tmp_path / "out.parquet",
            overwrite=True,
            fill_schema=True,
        )


def test_fill_depth_column_flag(admin_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    stitch(
        admin_input,
        output_path,
        overwrite=True,
        fill_schema=True,
        depth_column="adm_depth",
    )
    cols, _ = _columns_and_rows(output_path)
    assert "adm_depth" in cols
    assert "adm_lvl" not in cols


def test_depth_column_collision_raises(tmp_path):
    rows = [{**row, "adm_lvl": 99} for row in _ADMIN_ROWS]
    path = tmp_path / "collide.parquet"
    _write_admin_synthetic(path, rows)
    with pytest.raises(ValueError, match=r"adm_lvl.*already exists"):
        stitch(path, tmp_path / "out.parquet", overwrite=True, fill_schema=True)


def test_target_schema_path_requires_fill_schema(admin_input, tmp_path):
    with pytest.raises(ValueError, match="requires fill_schema"):
        stitch(
            admin_input,
            tmp_path / "out.parquet",
            overwrite=True,
            target_schema_path=DEFAULT_TARGET_SCHEMA_PATH,
        )
