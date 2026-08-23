"""Portability smoke tests for the standalone map() tool."""

import csv

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from topo_tools.api.map import map  # noqa: A004
from topo_tools.api.refactor import refactor
from topo_tools.cli.main import cli

_STEPS = ["inputs", "map", "outputs"]


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


def _crosswalk(path):
    with path.open(newline="") as f:
        return {row["source_column"]: row for row in csv.DictReader(f)}


@pytest.fixture
def chain_schema(tmp_path):
    """Naming templates decoupled from source names, level != source level."""
    return _write_schema(
        tmp_path / "chain_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )


@pytest.fixture
def chain_input(tmp_path):
    """2-level pcode chain, a name column, a non-nesting code, an unmatched column."""
    path = tmp_path / "chain.parquet"
    rows = [
        (_unit_square(0), "R0", "R0-1", "R0X1", "Alpha", "Miscellaneous One"),
        (_unit_square(1), "R0", "R0-1", "R0X2", "Alpha", "Miscellaneous Two"),
        (_unit_square(2), "R0", "R0-2", "R0X1", "Beta", "Miscellaneous Three"),
        (_unit_square(3), "R0", "R0-2", "R0X2", "Beta", "Miscellaneous One"),
    ]
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm1_pcode", "decoy_code", "adm1_name", "notes"],
        rows,
    )
    return path


@pytest.fixture
def noise_input(tmp_path):
    """Build a real 2-level chain plus GDAL/GIS bookkeeping noise columns."""
    path = tmp_path / "noise.parquet"
    rows = [
        (_unit_square(0), "R0", "R1", "1", "1", "1"),
        (_unit_square(1), "R0", "R1", "2", "2", "2"),
        (_unit_square(2), "R0", "R2", "3", "3", "3"),
        (_unit_square(3), "R0", "R2", "4", "4", "4"),
    ]
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm1_pcode", "OGC_FID", "ogc_fid_orig", "OBJECTID"],
        rows,
    )
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["map", "--help"])
    assert result.exit_code == 0
    assert "Map a source-column" in result.output
    assert "Examples:" in result.output


def test_code_and_name_tiers(chain_input, chain_schema, tmp_path):
    out = tmp_path / "crosswalk.csv"
    map(chain_input, chain_schema, out, overwrite=True)

    rows = _crosswalk(out)
    assert rows["adm0_pcode"]["target_column"] == ""
    assert rows["adm0_pcode"]["note"] == ""
    assert rows["adm1_pcode"]["target_column"] == "level1_pcode"
    assert rows["adm1_pcode"]["note"] == ""
    assert rows["adm1_pcode"]["unique_count"] == "2"
    assert rows["adm1_name"]["target_column"] == "level1_name"
    assert rows["adm1_name"]["note"] == ""
    assert rows["adm1_name"]["unique_count"] == "2"
    assert rows["decoy_code"]["target_column"] == ""
    assert rows["decoy_code"]["note"] == "ambiguous, level 1"
    assert rows["notes"]["target_column"] == ""
    assert rows["notes"]["note"] == ""


def test_unique_count_reveals_name_reused_across_parents(tmp_path):
    """Central repeats under both provinces: 3 raw names, 4 real units."""
    path = tmp_path / "reused_name.parquet"
    rows = [
        (_unit_square(0), "P1", "P101", "Central"),
        (_unit_square(1), "P1", "P102", "North"),
        (_unit_square(2), "P2", "P201", "Central"),
        (_unit_square(3), "P2", "P202", "South"),
    ]
    _write_table(path, ["geom", "adm0_pcode", "adm1_pcode", "adm1_name"], rows)
    out = tmp_path / "crosswalk.csv"
    map(path, output_path=out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_name"]["target_column"] == "adm1_name"
    assert rows_out["adm1_name"]["unique_count"] == "4"
    assert rows_out["adm1_pcode"]["unique_count"] == "4"


def test_noise_columns_excluded_entirely(noise_input, tmp_path):
    out = tmp_path / "crosswalk.csv"
    map(noise_input, output_path=out, overwrite=True)

    rows = _crosswalk(out)
    assert "OGC_FID" not in rows
    assert "ogc_fid_orig" not in rows
    assert "OBJECTID" not in rows


def test_output_ordering_level_desc_name_before_code_unmatched_last(
    chain_input, chain_schema, tmp_path
):
    out = tmp_path / "crosswalk.csv"
    map(chain_input, chain_schema, out, overwrite=True)

    with out.open(newline="") as f:
        ordered = [row["source_column"] for row in csv.DictReader(f)]
    assert ordered == ["adm1_name", "adm1_pcode", "decoy_code", "adm0_pcode", "notes"]


def test_target_schema_defaults_to_bundled_cod_ab(tmp_path):
    path = tmp_path / "cod_ab_like.parquet"
    rows = [
        (_unit_square(0), "MG", "MG1", "Alpha"),
        (_unit_square(1), "MG", "MG2", "Beta"),
    ]
    _write_table(path, ["geom", "adm0_pcode", "adm1_pcode", "adm1_name"], rows)
    out = tmp_path / "crosswalk.csv"
    map(path, output_path=out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_pcode"]["target_column"] == "adm1_pcode"
    assert rows_out["adm1_pcode"]["note"] == ""
    assert rows_out["adm1_pcode"]["unique_count"] == "2"
    assert rows_out["adm1_name"]["target_column"] == "adm1_name"
    assert rows_out["adm1_name"]["note"] == ""
    assert rows_out["adm1_name"]["unique_count"] == "2"


def test_cli_target_schema_defaults_to_bundled_cod_ab(tmp_path):
    path = tmp_path / "cod_ab_like.parquet"
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm0_name"],
        [(_unit_square(0), "MG0", "Madagascar")],
    )
    result = CliRunner().invoke(cli, ["map", str(path)])
    assert result.exit_code == 0, result.output

    out = path.with_stem(path.stem + "_crosswalk").with_suffix(".csv")
    rows = _crosswalk(out)
    assert rows["adm0_pcode"]["target_column"] == ""


def test_target_schema_missing_keys_raises(chain_input, tmp_path):
    schema_path = tmp_path / "bad_schema.yaml"
    schema_path.write_text(yaml.dump({"name_field": "adm{n}_name"}))
    with pytest.raises(
        ValueError, match="top-level 'name_field' and 'code_field' keys"
    ):
        map(chain_input, schema_path, overwrite=True)


def test_target_schema_missing_placeholder_raises(chain_input, tmp_path):
    schema_path = tmp_path / "bad_schema.yaml"
    schema_path.write_text(
        yaml.dump({"name_field": "adm_name", "code_field": "adm{n}_pcode"})
    )
    with pytest.raises(ValueError, match="must both contain a"):
        map(chain_input, schema_path, overwrite=True)


def test_default_output_path(chain_input, chain_schema):
    map(chain_input, chain_schema, overwrite=True)

    expected = chain_input.with_stem(chain_input.stem + "_crosswalk").with_suffix(
        ".csv"
    )
    assert expected.exists()


def test_cli_error_on_existing_output(chain_input, chain_schema, tmp_path):
    out = tmp_path / "exists.csv"
    out.touch()
    result = CliRunner().invoke(
        cli, ["map", str(chain_input), str(chain_schema), str(out), "--overwrite=false"]
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_map_steps(chain_input, chain_schema, tmp_path):
    out = tmp_path / "steps_crosswalk.csv"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        map(
            chain_input,
            chain_schema,
            out,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert out.exists()


def test_constant_bare_letter_code_reclassified(tmp_path):
    path = tmp_path / "bare.parquet"
    rows = [
        (_unit_square(0), "MG", "MG11", "Alpha"),
        (_unit_square(1), "MG", "MG11", "Alpha"),
        (_unit_square(2), "MG", "MG12", "Beta"),
        (_unit_square(3), "MG", "MG12", "Beta"),
    ]
    _write_table(path, ["geom", "adm0_pcode", "adm1_pcode", "adm1_name"], rows)
    schema = _write_schema(
        tmp_path / "bare_schema.yaml",
        name_field="adm{n}_name",
        code_field="adm{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_pcode"]["note"] == ""
    assert rows_out["adm1_pcode"]["unique_count"] == "2"
    assert rows_out["adm1_name"]["note"] == ""
    assert rows_out["adm1_name"]["unique_count"] == "2"


def test_name_bracket_group_numbers_multiple_name_candidates(tmp_path):
    path = tmp_path / "tie.parquet"
    rows = [
        (_unit_square(0), "R0", "R0R1", "Alpha", "TypeX"),
        (_unit_square(1), "R0", "R0R1", "Alpha", "TypeX"),
        (_unit_square(2), "R0", "R0R2", "Beta", "TypeY"),
        (_unit_square(3), "R0", "R0R2", "Beta", "TypeY"),
    ]
    _write_table(
        path, ["geom", "adm0_pcode", "adm1_pcode", "adm1_name", "tied_name"], rows
    )
    schema = _write_schema(
        tmp_path / "tie_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_name"]["target_column"] == "level1_name"
    assert rows_out["tied_name"]["target_column"] == "level1_name1"


def test_admin_level_zero_never_resolved(tmp_path):
    path = tmp_path / "level_zero.parquet"
    rows = [
        (_unit_square(0), "MG", "Madagascar", "MGR1", "Alpha"),
        (_unit_square(1), "MG", "Madagascar", "MGR1", "Alpha"),
        (_unit_square(2), "MG", "Madagascar", "MGR2", "Beta"),
        (_unit_square(3), "MG", "Madagascar", "MGR2", "Beta"),
    ]
    _write_table(
        path, ["geom", "adm0_pcode", "adm0_name", "adm1_pcode", "adm1_name"], rows
    )
    schema = _write_schema(
        tmp_path / "level_zero_schema.yaml",
        name_field="adm{n}_name",
        code_field="adm{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm0_pcode"]["target_column"] == ""
    assert rows_out["adm0_pcode"]["note"] == ""
    assert rows_out["adm0_name"]["target_column"] == ""
    assert rows_out["adm0_name"]["note"] == ""
    assert rows_out["adm1_pcode"]["note"] == ""
    assert rows_out["adm1_pcode"]["unique_count"] == "2"
    assert rows_out["adm1_name"]["note"] == ""
    assert rows_out["adm1_name"]["unique_count"] == "2"


def test_exact_bijective_match_wins_over_looser_function_match(tmp_path):
    path = tmp_path / "exact_match.parquet"
    rows = [
        (_unit_square(0), "R0", "R0R1", "Alpha", "Group1"),
        (_unit_square(1), "R0", "R0R2", "Beta", "Group1"),
        (_unit_square(2), "R0", "R0R3", "Gamma", "Group2"),
        (_unit_square(3), "R0", "R0R4", "Delta", "Group2"),
    ]
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm1_pcode", "adm1_name", "region_group"],
        rows,
    )
    schema = _write_schema(
        tmp_path / "exact_match_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_name"]["target_column"] == "level1_name"
    assert rows_out["region_group"]["target_column"] == ""
    assert rows_out["region_group"]["note"] == "supplemental, superset of level 1"


def test_code_bracket_group_numbers_bijective_code_companions(tmp_path):
    path = tmp_path / "code_companions.parquet"
    rows = [
        (_unit_square(0), "R0", "R0R1", "R0ALT1"),
        (_unit_square(1), "R0", "R0R1", "R0ALT1"),
        (_unit_square(2), "R0", "R0R2", "R0ALT2"),
        (_unit_square(3), "R0", "R0R2", "R0ALT2"),
    ]
    _write_table(path, ["geom", "adm0_pcode", "adm1_pcode", "alt1_pcode"], rows)
    schema = _write_schema(
        tmp_path / "code_companions_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_pcode"]["target_column"] == "level1_pcode"
    assert rows_out["alt1_pcode"]["target_column"] == "level1_pcode1"


def test_unedited_crosswalk_with_ambiguous_and_unmatched_survives_refactor(
    chain_input, chain_schema, tmp_path
):
    """An unedited crosswalk (blank-target columns dropped) must not raise."""
    crosswalk = tmp_path / "crosswalk.csv"
    map(chain_input, chain_schema, crosswalk, overwrite=True)

    out = tmp_path / "mapped.parquet"
    refactor(chain_input, crosswalk, out, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            r[0] for r in conn.execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall()
        }
    assert columns == {
        "level1_pcode",
        "level1_name",
        "geometry",
    }
