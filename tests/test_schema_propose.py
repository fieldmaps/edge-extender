"""Portability smoke tests for the standalone schema_propose() tool."""

import json

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from topo_tools.api.schema_apply import schema_apply
from topo_tools.api.schema_propose import schema_propose
from topo_tools.cli.main import cli
from topo_tools.core.schema_propose._02_propose import _order_and_validate

_STEPS = ["inputs", "propose", "outputs"]


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


def _write_schema(path, fields):
    path.write_text(yaml.dump({"fields": fields}))
    return path


def _unit_square(i):
    return f"POLYGON(({i} 0, {i + 1} 0, {i + 1} 1, {i} 1, {i} 0))"


def _crosswalk(path):
    return {row["source_column"]: row for row in json.loads(path.read_text())}


@pytest.fixture
def confidence_tiers_schema(tmp_path):
    return _write_schema(
        tmp_path / "schema.yaml",
        [
            {
                "name": "adm{n}_name",
                "repeatable": {"min": 0, "max": 2},
                "aliases": ["name"],
                "patterns": ["^adm[0-9]?_?name$"],
            },
            {"name": "iso3", "aliases": ["iso3"]},
            {"name": "survey_year", "patterns": ["year$"]},
        ],
    )


@pytest.fixture
def confidence_tiers_input(tmp_path):
    path = tmp_path / "confidence_tiers.parquet"
    _write_table(
        path,
        ["geom", "adm0_name", "iso3", "Rel_Year", "population"],
        [
            (_unit_square(0), "Testland", "TST", "2020", "100"),
            (_unit_square(1), "Testland", "TST", "2020", "200"),
        ],
    )
    return path


@pytest.fixture
def nesting_schema(tmp_path):
    return _write_schema(
        tmp_path / "nesting_schema.yaml",
        [
            {
                "name": "adm{n}_name",
                "repeatable": {"min": 0, "max": 5},
                "aliases": ["name"],
                "patterns": ["^nome_.*"],
            },
            {
                "name": "adm{n}_pcode",
                "repeatable": {"min": 0, "max": 5},
                "aliases": ["pcode"],
                "patterns": ["^cod_.*"],
            },
        ],
    )


@pytest.fixture
def nesting_input(tmp_path):
    """8 communes nested under 4 municipalities nested under 2 provinces.

    Cod_Com is the only pcode-role column (no Cod_Mun/Cod_Prov), exercising
    the single-candidate branch and the "name/pcode matched independently"
    design alongside the 3-level name chain.
    """
    path = tmp_path / "nesting.parquet"
    mun = ["M1", "M1", "M2", "M2", "M3", "M3", "M4", "M4"]
    prov = ["P1", "P1", "P1", "P1", "P2", "P2", "P2", "P2"]
    rows = [
        (_unit_square(i), f"C{i + 1}", f"K{i + 1}", mun[i], prov[i]) for i in range(8)
    ]
    _write_table(path, ["geom", "Nome_Com", "Cod_Com", "Nome_Mun", "Nome_Prov"], rows)
    return path


@pytest.fixture
def tie_schema(tmp_path):
    return _write_schema(
        tmp_path / "tie_schema.yaml",
        [
            {
                "name": "zone{n}_code",
                "repeatable": {"min": 0, "max": 3},
                "patterns": ["^zone_.*"],
            }
        ],
    )


@pytest.fixture
def tie_input(tmp_path):
    """Zone_A and Zone_B both have 2 distinct values: a cardinality tie."""
    path = tmp_path / "tie.parquet"
    rows = [
        (_unit_square(0), "X", "P"),
        (_unit_square(1), "X", "Q"),
        (_unit_square(2), "Y", "P"),
        (_unit_square(3), "Y", "Q"),
    ]
    _write_table(path, ["geom", "Zone_A", "Zone_B"], rows)
    return path


@pytest.fixture
def containment_failure_schema(tmp_path):
    return _write_schema(
        tmp_path / "bad_schema.yaml",
        [
            {
                "name": "bad{n}_code",
                "repeatable": {"min": 0, "max": 3},
                "patterns": ["^bad_.*"],
            }
        ],
    )


@pytest.fixture
def containment_failure_input(tmp_path):
    """Bad_Fine's value 'w' spans two Bad_Coarse values: containment fails."""
    path = tmp_path / "containment_failure.parquet"
    rows = [
        (_unit_square(0), "A", "w"),
        (_unit_square(1), "B", "w"),
        (_unit_square(2), "A", "x"),
        (_unit_square(3), "B", "y"),
    ]
    _write_table(path, ["geom", "Bad_Coarse", "Bad_Fine"], rows)
    return path


def test_cli_help():
    result = CliRunner().invoke(cli, ["schema-propose", "--help"])
    assert result.exit_code == 0
    assert "Propose a source-column" in result.output
    assert "Examples:" in result.output


def test_confidence_tiers(confidence_tiers_input, confidence_tiers_schema, tmp_path):
    out = tmp_path / "crosswalk.json"
    schema_propose(confidence_tiers_input, confidence_tiers_schema, out, overwrite=True)

    rows = _crosswalk(out)
    assert rows["adm0_name"]["target_column"] == "adm0_name"
    assert rows["adm0_name"]["confidence"] == "exact"
    assert rows["iso3"]["target_column"] == "iso3"
    assert rows["iso3"]["confidence"] == "exact"
    assert rows["Rel_Year"]["target_column"] == "survey_year"
    assert rows["Rel_Year"]["confidence"] == "pattern"
    assert rows["population"]["target_column"] == "population"
    assert rows["population"]["confidence"] == "unmatched"


def test_nesting_chain_with_own_level(nesting_input, nesting_schema, tmp_path):
    out = tmp_path / "crosswalk.json"
    schema_propose(nesting_input, nesting_schema, out, own_level=4, overwrite=True)

    rows = _crosswalk(out)
    assert rows["Nome_Com"]["target_column"] == "adm4_name"
    assert rows["Nome_Com"]["confidence"] == "exact"
    assert rows["Nome_Mun"]["target_column"] == "Nome_Mun"
    assert rows["Nome_Mun"]["confidence"] == "nesting-validated-relative"
    assert "coarser than Nome_Com" in rows["Nome_Mun"]["note"]
    assert rows["Nome_Prov"]["target_column"] == "Nome_Prov"
    assert rows["Nome_Prov"]["confidence"] == "nesting-validated-relative"
    assert "coarser than Nome_Mun" in rows["Nome_Prov"]["note"]
    # Sole pcode-role candidate: anchored the same way as the finest name column.
    assert rows["Cod_Com"]["target_column"] == "adm4_pcode"
    assert rows["Cod_Com"]["confidence"] == "exact"


def test_nesting_chain_without_own_level(nesting_input, nesting_schema, tmp_path):
    out = tmp_path / "crosswalk.json"
    schema_propose(nesting_input, nesting_schema, out, overwrite=True)

    rows = _crosswalk(out)
    for col in ("Nome_Com", "Nome_Mun", "Nome_Prov", "Cod_Com"):
        assert rows[col]["target_column"] == col
        assert rows[col]["confidence"] == "nesting-validated-relative"
    assert "finest in this chain" in rows["Nome_Com"]["note"]
    assert "sole candidate" in rows["Cod_Com"]["note"]


def test_nesting_chain_unedited_crosswalk_survives_schema_apply(
    nesting_input, nesting_schema, tmp_path
):
    """An unedited crosswalk from schema-propose must never drop data."""
    crosswalk = tmp_path / "crosswalk.json"
    schema_propose(nesting_input, nesting_schema, crosswalk, overwrite=True)

    out = tmp_path / "mapped.parquet"
    schema_apply(nesting_input, crosswalk, out, overwrite=True)

    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        columns = {
            r[0] for r in conn.execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall()
        }
    assert {"Nome_Com", "Nome_Mun", "Nome_Prov", "Cod_Com"} <= columns


def test_own_level_out_of_repeatable_range_raises(nesting_input, nesting_schema):
    with pytest.raises(ValueError, match="declared repeatable range"):
        schema_propose(nesting_input, nesting_schema, own_level=12, overwrite=True)


def test_order_and_validate_handles_quoted_column_name():
    with duckdb.connect() as conn:
        conn.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES "
            "(1, 'x'), (1, 'y'), (2, 'z')"
            ') AS v(coarse, "fine""col")'
        )
        ordered, valid = _order_and_validate(conn, "t", ["coarse", 'fine"col'])
    assert valid
    assert ordered == ["coarse", 'fine"col']


def test_nesting_tie_falls_back_to_ambiguous(tie_input, tie_schema, tmp_path):
    out = tmp_path / "crosswalk.json"
    schema_propose(tie_input, tie_schema, out, overwrite=True)

    rows = _crosswalk(out)
    for col in ("Zone_A", "Zone_B"):
        assert rows[col]["target_column"] == col
        assert rows[col]["confidence"] == "ambiguous"
        assert "cannot order automatically" in rows[col]["note"]


def test_nesting_containment_failure_falls_back_to_ambiguous(
    containment_failure_input, containment_failure_schema, tmp_path
):
    out = tmp_path / "crosswalk.json"
    schema_propose(
        containment_failure_input, containment_failure_schema, out, overwrite=True
    )

    rows = _crosswalk(out)
    for col in ("Bad_Coarse", "Bad_Fine"):
        assert rows[col]["confidence"] == "ambiguous"


def test_default_output_path(confidence_tiers_input, confidence_tiers_schema):
    schema_propose(confidence_tiers_input, confidence_tiers_schema, overwrite=True)

    expected = confidence_tiers_input.with_stem(
        confidence_tiers_input.stem + "_crosswalk"
    ).with_suffix(".json")
    assert expected.exists()


def test_own_level_must_be_non_negative(
    confidence_tiers_input, confidence_tiers_schema
):
    with pytest.raises(ValueError, match="own_level must be non-negative"):
        schema_propose(
            confidence_tiers_input,
            confidence_tiers_schema,
            own_level=-1,
            overwrite=True,
        )


def test_target_schema_missing_fields_key_raises(confidence_tiers_input, tmp_path):
    schema_path = tmp_path / "bad_schema.yaml"
    schema_path.write_text(yaml.dump({"field": []}))
    with pytest.raises(ValueError, match="top-level 'fields' key"):
        schema_propose(confidence_tiers_input, schema_path, overwrite=True)


def test_target_schema_field_missing_name_raises(confidence_tiers_input, tmp_path):
    schema_path = tmp_path / "bad_schema.yaml"
    schema_path.write_text(yaml.dump({"fields": [{"aliases": ["iso3"]}]}))
    with pytest.raises(ValueError, match="missing required 'name' key"):
        schema_propose(confidence_tiers_input, schema_path, overwrite=True)


def test_target_schema_repeatable_missing_max_raises(confidence_tiers_input, tmp_path):
    schema_path = tmp_path / "bad_schema.yaml"
    schema_path.write_text(
        yaml.dump({"fields": [{"name": "adm{n}_name", "repeatable": {"min": 0}}]})
    )
    with pytest.raises(ValueError, match="repeatable block missing min/max"):
        schema_propose(confidence_tiers_input, schema_path, overwrite=True)


def test_cli_error_on_existing_output(
    confidence_tiers_input, confidence_tiers_schema, tmp_path
):
    out = tmp_path / "exists.json"
    out.touch()
    result = CliRunner().invoke(
        cli,
        [
            "schema-propose",
            str(confidence_tiers_input),
            str(confidence_tiers_schema),
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "output already exists" in result.output


def test_schema_propose_steps(
    confidence_tiers_input, confidence_tiers_schema, tmp_path
):
    out = tmp_path / "steps_crosswalk.json"
    work_dir = tmp_path / "work"
    for step in _STEPS:
        schema_propose(
            confidence_tiers_input,
            confidence_tiers_schema,
            out,
            tmp_dir=work_dir,
            step=step,
            overwrite=True,
        )
    assert out.exists()
