"""Portability smoke tests for the standalone fill() tool."""

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from topo_tools.api.dissolve import dissolve
from topo_tools.api.schema_fill import fill
from topo_tools.cli.main import cli
from topo_tools.core.schema_map._target_schema import DEFAULT_TARGET_SCHEMA_PATH

_STEPS = ["inputs", "fill", "outputs"]
_LEVEL_1, _LEVEL_2, _LEVEL_3 = 1, 2, 3

_LEAF_ROWS = [
    {
        "adm1_pcode": "AA",
        "adm1_name": "Country A",
        "adm2_pcode": "AA01",
        "adm2_name": "Prov1",
        "adm3_pcode": "AA0101",
        "adm3_name": "Dist1",
        "wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
    },
    {
        "adm1_pcode": "AA",
        "adm1_name": "Country A",
        "adm2_pcode": "AA02",
        "adm2_name": "Prov2",
        "adm3_pcode": None,
        "adm3_name": None,
        "wkt": "POLYGON((0 1, 1 1, 1 2, 0 2, 0 1))",
    },
    {
        "adm1_pcode": "BB",
        "adm1_name": "Country B",
        "adm2_pcode": None,
        "adm2_name": None,
        "adm3_pcode": None,
        "adm3_name": None,
        "wkt": "POLYGON((5 5, 6 5, 6 6, 5 6, 5 5))",
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


def _write_schema(path, name_field, code_field):
    path.write_text(yaml.dump({"name_field": name_field, "code_field": code_field}))
    return path


def _fetch(path):
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT * EXCLUDE (geometry) FROM '{path}' ORDER BY adm1_pcode, "
            "adm2_pcode, adm3_pcode"
        ).fetchall()
        cols = [d[0] for d in conn.description]
    return cols, {r[0:3]: r for r in rows}


@pytest.fixture
def leaf_input(tmp_path):
    path = tmp_path / "leaf.parquet"
    _write_synthetic(path, _LEAF_ROWS)
    return path


@pytest.fixture
def admin1_only_input(tmp_path):
    path = tmp_path / "leaf1.parquet"
    rows = [
        {"adm1_pcode": "AA", "adm1_name": "Country A", "wkt": _LEAF_ROWS[0]["wkt"]},
        {"adm1_pcode": "BB", "adm1_name": "Country B", "wkt": _LEAF_ROWS[2]["wkt"]},
    ]
    _write_synthetic(path, rows)
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["schema-fill", "--help"])
    assert result.exit_code == 0
    assert "Cascade each admin-hierarchy column" in result.output


def test_fills_down_and_stamps_depth(leaf_input, tmp_path):
    output_path = tmp_path / "out.parquet"
    fill(leaf_input, output_path=output_path, overwrite=True)

    cols, by_code = _fetch(output_path)
    assert "adm_lvl" in cols
    lvl = cols.index("adm_lvl")
    name3 = cols.index("adm3_name")

    row_aa0101 = by_code[("AA", "AA01", "AA0101")]
    assert row_aa0101[lvl] == _LEVEL_3

    row_aa02 = by_code[("AA", "AA02", "AA02")]
    assert row_aa02[lvl] == _LEVEL_2
    assert row_aa02[name3] == "Prov2"

    row_bb = by_code[("BB", "BB", "BB")]
    assert row_bb[lvl] == _LEVEL_1
    assert row_bb[name3] == "Country B"


def test_extends_to_a_single_level(admin1_only_input, tmp_path):
    output_path = tmp_path / "out1.parquet"
    fill(admin1_only_input, output_path=output_path, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT adm1_pcode, adm_lvl FROM '{output_path}' ORDER BY adm1_pcode"
        ).fetchall()
    assert rows == [("AA", 1), ("BB", 1)]


def test_missing_level_column_raises(tmp_path):
    path = tmp_path / "missing_level.parquet"
    rows = [{k: v for k, v in row.items() if k != "adm2_pcode"} for row in _LEAF_ROWS]
    _write_synthetic(path, rows)
    with pytest.raises(ValueError, match="missing code column"):
        fill(path, overwrite=True)


def test_default_output_path(leaf_input):
    fill(leaf_input, overwrite=True)
    assert leaf_input.with_stem(leaf_input.stem + "_fill").exists()


def test_steps(leaf_input, tmp_path):
    output_path = tmp_path / "steps_out.parquet"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        fill(
            leaf_input,
            output_path=output_path,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert output_path.exists()


def test_custom_target_schema(tmp_path):
    schema_path = _write_schema(
        tmp_path / "custom_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_id",
    )
    rows = [
        {
            "level1_id": "X1",
            "level1_name": "Region1",
            "level2_id": "X101",
            "level2_name": "District1",
            "wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        },
    ]
    input_path = tmp_path / "custom_leaf.parquet"
    _write_synthetic(input_path, rows)

    output_path = tmp_path / "custom_out.parquet"
    fill(
        input_path,
        target_schema_path=schema_path,
        output_path=output_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        cols = {
            row[0]
            for row in conn.execute(
                f"DESCRIBE SELECT * FROM '{output_path}'"
            ).fetchall()
        }
    assert "adm_lvl" in cols


def test_mismatched_name_code_prefixes_both_fill(tmp_path):
    """name_field and code_field with unrelated prefixes must both cascade."""
    schema_path = _write_schema(
        tmp_path / "gadm_schema.yaml", name_field="NAME_{n}", code_field="GID_{n}"
    )
    rows = [
        {
            "GID_1": "X1",
            "NAME_1": "Region1",
            "GID_2": "X101",
            "NAME_2": "District1",
            "wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        },
        {
            "GID_1": "X1",
            "NAME_1": "Region1",
            "GID_2": "X102",
            "NAME_2": None,
            "wkt": "POLYGON((0 1, 1 1, 1 2, 0 2, 0 1))",
        },
    ]
    input_path = tmp_path / "gadm_leaf.parquet"
    _write_synthetic(input_path, rows)

    output_path = tmp_path / "gadm_out.parquet"
    fill(
        input_path,
        target_schema_path=schema_path,
        output_path=output_path,
        overwrite=True,
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        result = conn.execute(
            f"SELECT NAME_2, adm_lvl FROM '{output_path}' ORDER BY GID_2"
        ).fetchall()
    assert result == [("District1", _LEVEL_2), ("Region1", _LEVEL_2)]


def test_custom_depth_column_name(leaf_input, tmp_path):
    output_path = tmp_path / "custom_depth_out.parquet"
    fill(leaf_input, output_path=output_path, overwrite=True, depth_column="my_depth")

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        cols = {
            row[0]
            for row in conn.execute(
                f"DESCRIBE SELECT * FROM '{output_path}'"
            ).fetchall()
        }
    assert "my_depth" in cols
    assert "adm_lvl" not in cols


def test_dissolve_after_fill_keeps_lvl_column(leaf_input, tmp_path):
    """Once filled, plain dissolve builds each level, auto-keeping adm_lvl."""
    filled_path = tmp_path / "filled.parquet"
    fill(leaf_input, output_path=filled_path, overwrite=True)

    adm2_path = tmp_path / "adm2.parquet"
    dissolve(
        filled_path, adm2_path, group_by=["adm2_pcode", "adm1_pcode"], overwrite=True
    )

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        rows = conn.execute(
            f"SELECT adm2_pcode, adm_lvl FROM '{adm2_path}' ORDER BY adm2_pcode"
        ).fetchall()
    assert rows == [("AA01", 3), ("AA02", 2), ("BB", 1)]


def test_cli_positional_args(leaf_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli, ["schema-fill", str(leaf_input), "", str(output_path)]
    )
    assert result.exit_code != 0
    assert "target schema file not found" in result.output


def test_cli_default_schema(leaf_input, tmp_path):
    output_path = tmp_path / "cli_out.parquet"
    result = CliRunner().invoke(
        cli,
        [
            "schema-fill",
            str(leaf_input),
            str(DEFAULT_TARGET_SCHEMA_PATH),
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.exists()


def test_cli_error_on_existing_output(leaf_input, tmp_path):
    output_path = tmp_path / "exists.parquet"
    output_path.touch()
    result = CliRunner().invoke(
        cli,
        [
            "schema-fill",
            str(leaf_input),
            str(DEFAULT_TARGET_SCHEMA_PATH),
            str(output_path),
            "--overwrite=false",
        ],
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output
