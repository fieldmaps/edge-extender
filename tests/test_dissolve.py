"""Portability smoke tests: does dissolve() run to completion on this machine.

Not a topology/correctness suite: outputs.main already raises RuntimeError
on coverage violations, so a run that completes without raising has already
been vetted for correctness by the pipeline itself.
"""

import duckdb
import pytest
from click.testing import CliRunner

from topo_tools.api.dissolve import dissolve
from topo_tools.cli.main import cli

_STEPS = ["inputs", "dissolve", "outputs"]

_BASE_ROWS = [
    {
        "adm2_pcode": "A1",
        "adm1_pcode": "P1",
        "adm2_name": "Alpha",
        "adm1_name": "Province1",
        "population": 100,
        "wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
    },
    {
        "adm2_pcode": "A1",
        "adm1_pcode": "P1",
        "adm2_name": "Alpha",
        "adm1_name": "Province1",
        "population": 150,
        "wkt": "POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))",
    },
    {
        "adm2_pcode": "A2",
        "adm1_pcode": "P1",
        "adm2_name": "Beta",
        "adm1_name": "Province1",
        "population": 80,
        "wkt": "POLYGON((0 1, 1 1, 1 2, 0 2, 0 1))",
    },
]


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return f"'{value}'"
    return str(value)


def _write_synthetic(path, rows: list[dict]) -> None:
    cols = [k for k in rows[0] if k != "wkt"]
    col_list = ", ".join([*cols, "geom"])
    values = ", ".join(
        "("
        + ", ".join(_sql_literal(r[c]) for c in cols)
        + f", ST_GeomFromText('{r['wkt']}'))"
        for r in rows
    )
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t({col_list})"
        )
        conn.execute(f"COPY synth TO '{path}'")


@pytest.fixture
def admin3_input(tmp_path):
    path = tmp_path / "admin3.parquet"
    _write_synthetic(path, _BASE_ROWS)
    return path


@pytest.fixture
def admin3_with_null(tmp_path):
    path = tmp_path / "admin3_null.parquet"
    null_row = {
        "adm2_pcode": None,
        "adm1_pcode": "P1",
        "adm2_name": None,
        "adm1_name": "Province1",
        "population": 20,
        "wkt": "POLYGON((2 0, 3 0, 3 1, 2 1, 2 0))",
    }
    _write_synthetic(path, [*_BASE_ROWS, null_row])
    return path


@pytest.fixture
def admin3_inconsistent_name(tmp_path):
    path = tmp_path / "admin3_inconsistent.parquet"
    rows = [dict(_BASE_ROWS[0]), dict(_BASE_ROWS[1]), dict(_BASE_ROWS[2])]
    rows[1]["adm2_name"] = "AlphaTypo"
    _write_synthetic(path, rows)
    return path


def _describe_columns(path) -> set[str]:
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        return {
            row[0]
            for row in conn.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()
        }


def test_cli_help():
    result = CliRunner().invoke(cli, ["dissolve", "--help"])
    assert result.exit_code == 0
    assert "Aggregate a polygon layer" in result.output
    assert "Examples:" in result.output


def test_dissolve_auto_keeps_constant_drops_non_constant(admin3_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    dissolve(
        admin3_input,
        output_path,
        group_by=["adm2_pcode", "adm1_pcode"],
        overwrite=True,
    )

    assert output_path.exists()
    expected_row_count = 2
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count
    # adm2_name/adm1_name are constant per group and auto-kept; population
    # varies within group A1 (100 vs 150) and is auto-dropped.
    assert _describe_columns(output_path) == {
        "adm2_pcode",
        "adm1_pcode",
        "adm2_name",
        "adm1_name",
        "geometry",
    }


def test_dissolve_auto_drops_inconsistent_column_with_warning(
    admin3_inconsistent_name, tmp_path, caplog
):
    output_path = tmp_path / "out.parquet"
    with caplog.at_level("WARNING"):
        dissolve(
            admin3_inconsistent_name,
            output_path,
            group_by=["adm2_pcode", "adm1_pcode"],
            overwrite=True,
        )

    assert "adm2_name" not in _describe_columns(output_path)
    assert "adm1_name" in _describe_columns(output_path)
    assert any("adm2_name" in record.message for record in caplog.records)


def test_dissolve_null_group_forms_own_group(admin3_with_null, tmp_path):
    output_path = tmp_path / "out.parquet"
    dissolve(
        admin3_with_null,
        output_path,
        group_by=["adm2_pcode", "adm1_pcode"],
        overwrite=True,
    )

    # A1/P1, A2/P1, and NULL/P1 (the row lacking an adm2_pcode) each form
    # their own group, matching GDAL's `combine --group-by` semantics.
    expected_row_count = 3
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0]
    assert row_count == expected_row_count


def test_dissolve_missing_group_by_column_raises(admin3_input):
    with pytest.raises(ValueError, match="column\\(s\\) not found"):
        dissolve(admin3_input, group_by=["nonexistent_col"], overwrite=True)


def test_dissolve_requires_non_empty_group_by(admin3_input):
    with pytest.raises(ValueError, match="group_by must be a non-empty list"):
        dissolve(admin3_input, group_by=[], overwrite=True)


def test_dissolve_default_output_path(admin3_input):
    dissolve(admin3_input, group_by=["adm2_pcode", "adm1_pcode"], overwrite=True)

    expected = admin3_input.with_stem(admin3_input.stem + "_dissolved")
    assert expected.exists()


def test_dissolve_steps(admin3_input, tmp_path):
    """Each pipeline stage runs standalone, reusing one tmp_dir's DuckDB file."""
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        dissolve(
            admin3_input,
            output_path,
            group_by=["adm2_pcode", "adm1_pcode"],
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()


def test_cli_positional_args_and_group_by_option(admin3_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "dissolve",
            str(admin3_input),
            str(output_path),
            "--group-by",
            "adm2_pcode,adm1_pcode",
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_missing_group_by_errors(admin3_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(cli, ["dissolve", str(admin3_input), str(output_path)])
    assert result.exit_code != 0
    assert "--group-by" in result.output


def test_cli_error_on_existing_output(admin3_input, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        [
            "dissolve",
            str(admin3_input),
            str(output_path),
            "--group-by",
            "adm2_pcode,adm1_pcode",
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "output already exists" in result.output
