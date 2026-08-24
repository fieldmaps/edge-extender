"""Portability smoke tests for the composite crosswalk() tool (map + refactor)."""

import csv

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from topo_tools.api.schema_crosswalk import crosswalk
from topo_tools.cli.main import cli

_STEPS = ["inputs", "map", "apply", "outputs"]


def _write_table(path, col_names, rows):
    def _cell(col, val):
        if col == "geom":
            return f"ST_GeomFromText('{val}')"
        return "NULL" if val is None else f"'{val}'"

    values = ", ".join(
        "(" + ", ".join(_cell(c, v) for c, v in zip(col_names, row, strict=True)) + ")"
        for row in rows
    )
    cols_decl = ", ".join(col_names)
    with duckdb.connect() as conn:
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"CREATE TABLE synth AS SELECT * FROM (VALUES {values}) AS t({cols_decl})"
        )
        conn.execute(f"COPY synth TO '{path}'")


def _write_schema(path, name_field, code_field):
    path.write_text(yaml.dump({"name_field": name_field, "code_field": code_field}))
    return path


def _unit_square(i):
    return f"POLYGON(({i} 0, {i + 1} 0, {i + 1} 1, {i} 1, {i} 0))"


def _crosswalk_rows(path):
    with path.open(newline="") as f:
        return {row["source_column"]: row for row in csv.DictReader(f)}


@pytest.fixture
def structural_hierarchy_input(tmp_path):
    """GRID3-style hierarchy (name/code pairs, two levels) plus GIS noise columns."""
    path = tmp_path / "structural.parquet"
    rows = [
        (
            _unit_square(0),
            "Province One",
            "PU1",
            "Zone Alpha",
            "PU1ZU1",
            "1",
            "1.5",
            "2.5",
        ),
        (
            _unit_square(1),
            "Province One",
            "PU1",
            "Zone Beta",
            "PU1ZU2",
            "2",
            "1.5",
            "2.5",
        ),
        (
            _unit_square(2),
            "Province Two",
            "PU2",
            "Zone Gamma",
            "PU2ZU3",
            "3",
            "1.5",
            "2.5",
        ),
        (
            _unit_square(3),
            "Province Two",
            "PU2",
            "Zone Delta",
            "PU2ZU4",
            "4",
            "1.5",
            "2.5",
        ),
    ]
    _write_table(
        path,
        [
            "geom",
            "province",
            "prov_uid",
            "zonesante",
            "zs_uid",
            "OBJECTID",
            "Shape_Length",
            "Shape_Area",
        ],
        rows,
    )
    return path


@pytest.fixture
def structural_hierarchy_schema(tmp_path):
    """Naming templates only; map infers structure without reading these."""
    return _write_schema(
        tmp_path / "structural_schema.yaml",
        name_field="adm{n}_name",
        code_field="adm{n}_pcode",
    )


def test_cli_help():
    result = CliRunner().invoke(cli, ["schema-crosswalk", "--help"])
    assert result.exit_code == 0
    assert "schema-map + schema-refactor, combined" in result.output
    assert "Examples:" in result.output


def test_end_to_end_writes_crosswalk_and_mapped_output(
    structural_hierarchy_input, structural_hierarchy_schema, tmp_path
):
    crosswalk_out = tmp_path / "out_crosswalk.csv"
    mapped_out = tmp_path / "out_mapped.parquet"
    crosswalk(
        structural_hierarchy_input,
        structural_hierarchy_schema,
        mapped_out,
        crosswalk_out,
        overwrite=True,
    )

    rows = _crosswalk_rows(crosswalk_out)
    assert rows["province"]["target_column"] == "adm0_name"
    assert rows["province"]["note"] == ""
    assert rows["prov_uid"]["target_column"] == "adm0_pcode"
    assert rows["prov_uid"]["note"] == ""
    assert rows["zonesante"]["target_column"] == "adm1_name"
    assert rows["zs_uid"]["target_column"] == "adm1_pcode"
    assert "OBJECTID" not in rows
    assert "Shape_Length" not in rows

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            r[0]
            for r in conn.execute(f"DESCRIBE SELECT * FROM '{mapped_out}'").fetchall()
        }
        values = conn.execute(
            f"SELECT adm1_name FROM '{mapped_out}' ORDER BY adm1_pcode"
        ).fetchall()
    assert columns == {
        "adm0_name",
        "adm0_pcode",
        "adm1_name",
        "adm1_pcode",
        "geometry",
    }
    assert values == [
        ("Zone Alpha",),
        ("Zone Beta",),
        ("Zone Gamma",),
        ("Zone Delta",),
    ]


def test_default_output_paths(structural_hierarchy_input, structural_hierarchy_schema):
    crosswalk(structural_hierarchy_input, structural_hierarchy_schema, overwrite=True)

    expected_mapped = structural_hierarchy_input.with_stem(
        structural_hierarchy_input.stem + "_mapped"
    )
    expected_crosswalk = structural_hierarchy_input.with_stem(
        structural_hierarchy_input.stem + "_crosswalk"
    ).with_suffix(".csv")
    assert expected_mapped.exists()
    assert expected_crosswalk.exists()


def test_overwrite_required_for_both_outputs(
    structural_hierarchy_input, structural_hierarchy_schema, tmp_path
):
    crosswalk_out = tmp_path / "out_crosswalk.csv"
    mapped_out = tmp_path / "out_mapped.parquet"
    crosswalk(
        structural_hierarchy_input,
        structural_hierarchy_schema,
        mapped_out,
        crosswalk_out,
    )

    with pytest.raises(FileExistsError, match="output already exists"):
        crosswalk(
            structural_hierarchy_input,
            structural_hierarchy_schema,
            mapped_out,
            crosswalk_out,
            overwrite=False,
        )

    crosswalk(
        structural_hierarchy_input,
        structural_hierarchy_schema,
        mapped_out,
        crosswalk_out,
    )


def test_cli_error_on_existing_output(
    structural_hierarchy_input, structural_hierarchy_schema, tmp_path
):
    mapped_out = tmp_path / "exists.parquet"
    mapped_out.touch()
    result = CliRunner().invoke(
        cli,
        [
            "schema-crosswalk",
            str(structural_hierarchy_input),
            str(structural_hierarchy_schema),
            str(mapped_out),
            "--overwrite=false",
        ],
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_crosswalk_steps(
    structural_hierarchy_input, structural_hierarchy_schema, tmp_path
):
    mapped_out = tmp_path / "steps_mapped.parquet"
    crosswalk_out = tmp_path / "steps_crosswalk.csv"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        crosswalk(
            structural_hierarchy_input,
            structural_hierarchy_schema,
            mapped_out,
            crosswalk_out,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert mapped_out.exists()
    assert crosswalk_out.exists()
