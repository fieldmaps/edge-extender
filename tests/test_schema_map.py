"""Portability smoke tests for the standalone map() tool."""

import csv

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from topo_tools.api.schema_map import map  # noqa: A004
from topo_tools.api.schema_refactor import refactor
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
    result = CliRunner().invoke(cli, ["schema-map", "--help"])
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


def test_target_schema_defaults_to_bundled_default(tmp_path):
    path = tmp_path / "cod_ab_like.parquet"
    rows = [
        (_unit_square(0), "MG", "MG1", "Alpha"),
        (_unit_square(1), "MG", "MG2", "Beta"),
    ]
    _write_table(path, ["geom", "adm0_pcode", "adm1_pcode", "adm1_name"], rows)
    out = tmp_path / "crosswalk.csv"
    map(path, output_path=out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_pcode"]["target_column"] == "adm1_code"
    assert rows_out["adm1_pcode"]["note"] == ""
    assert rows_out["adm1_pcode"]["unique_count"] == "2"
    assert rows_out["adm1_name"]["target_column"] == "adm1_name"
    assert rows_out["adm1_name"]["note"] == ""
    assert rows_out["adm1_name"]["unique_count"] == "2"


def test_cli_target_schema_defaults_to_bundled_default(tmp_path):
    path = tmp_path / "cod_ab_like.parquet"
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm0_name"],
        [(_unit_square(0), "MG0", "Madagascar")],
    )
    result = CliRunner().invoke(cli, ["schema-map", str(path)])
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


def test_target_schema_not_a_file_raises(chain_input, tmp_path):
    with pytest.raises(ValueError, match="target schema file not found"):
        map(chain_input, tmp_path, overwrite=True)


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
        cli,
        [
            "schema-map",
            str(chain_input),
            str(chain_schema),
            str(out),
            "--overwrite=false",
        ],
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


def _twenty_unit_rows(cand_values):
    """20 admin1 units (bijective pcode/name), plus one candidate column.

    adm1_name uses letters, not digits, so it isn't mistaken for code-shaped.
    """
    return [
        (_unit_square(i), "R0", f"R0R{i}", f"Region{chr(64 + i)}", cand_values[i - 1])
        for i in range(1, 21)
    ]


def _write_twenty_unit_table(tmp_path, name, cand_values):
    path = tmp_path / f"{name}.parquet"
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm1_pcode", "adm1_name", "alt_name"],
        _twenty_unit_rows(cand_values),
    )
    schema = _write_schema(
        tmp_path / f"{name}_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )
    return path, schema


def test_near_bijective_alt_name_becomes_numbered_sibling(tmp_path):
    """A 5%-collapse candidate (1 coincidental duplicate) still numbers as name1."""
    values = [f"Nom{i}" for i in range(1, 21)]
    values[1] = values[0]  # Nom1 reused for unit 2: 19/20 distinct, 5% collapse.
    path, schema = _write_twenty_unit_table(tmp_path, "near_bijective", values)
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["adm1_name"]["target_column"] == "level1_name"
    assert rows_out["alt_name"]["target_column"] == "level1_name1"
    assert rows_out["alt_name"]["note"] == ""


def test_collapse_over_threshold_stays_supplemental(tmp_path):
    """A 65%-collapse candidate (Algeria-shaped) is still a coarser grouping."""
    values = [f"Group{(i - 1) % 7}" for i in range(1, 21)]  # 7/20 distinct, 65%.
    path, schema = _write_twenty_unit_table(tmp_path, "coarse_collapse", values)
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    assert rows_out["alt_name"]["target_column"] == ""
    assert rows_out["alt_name"]["note"] == "supplemental, superset of level 1"


def test_collapse_near_threshold_boundary(tmp_path):
    """Pins the 0.30 cutoff region: 25% numbered, 35% stays supplemental.

    Avoids testing the literal 0.30 value itself: 1 - 14/20 float-rounds to
    0.30000000000000004, an unreliable equality to assert against.
    """
    numbered_values = [f"Nom{(i - 1) % 15}" for i in range(1, 21)]  # 15/20, 25%.
    path, schema = _write_twenty_unit_table(tmp_path, "under_boundary", numbered_values)
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)
    rows_out = _crosswalk(out)
    assert rows_out["alt_name"]["target_column"] == "level1_name1"

    over_values = [f"Nom{(i - 1) % 13}" for i in range(1, 21)]  # 13/20, 35%.
    path2, schema2 = _write_twenty_unit_table(tmp_path, "over_boundary", over_values)
    out2 = tmp_path / "crosswalk2.csv"
    map(path2, schema2, out2, overwrite=True)
    rows_out2 = _crosswalk(out2)
    assert rows_out2["alt_name"]["target_column"] == ""
    assert rows_out2["alt_name"]["note"] == "supplemental, superset of level 1"


def test_two_tolerated_siblings_get_sequential_numbering_no_collision(tmp_path):
    """Two in-tolerance bracket winners at an already-named level don't collide."""
    path = tmp_path / "two_siblings.parquet"
    values1 = [f"Nom{i}" for i in range(1, 21)]
    values1[1] = values1[0]  # 19/20 distinct.
    values2 = [f"Autre{i}" for i in range(1, 21)]
    values2[1] = values2[0]
    values2[3] = values2[2]  # 18/20 distinct.
    rows = [(*row, values2[i]) for i, row in enumerate(_twenty_unit_rows(values1))]
    _write_table(
        path,
        ["geom", "adm0_pcode", "adm1_pcode", "adm1_name", "alt_name1", "alt_name2"],
        rows,
    )
    schema = _write_schema(
        tmp_path / "two_siblings_schema.yaml",
        name_field="level{n}_name",
        code_field="level{n}_pcode",
    )
    out = tmp_path / "crosswalk.csv"
    map(path, schema, out, overwrite=True)

    rows_out = _crosswalk(out)
    targets = {
        rows_out["adm1_name"]["target_column"],
        rows_out["alt_name1"]["target_column"],
        rows_out["alt_name2"]["target_column"],
    }
    assert targets == {"level1_name", "level1_name1", "level1_name2"}


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
