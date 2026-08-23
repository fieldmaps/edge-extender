# Manually test any tool against your own data

Every tool (released or not) is a normal CLI command once you're on this
checkout, whether or not it's in a tagged release yet.

## Run via CLI

```bash
uv run topo-tools <tool> <args...>
```

e.g. `uv run topo-tools dissolve my_layer.gpkg --group-by adm2_pcode`. Args
differ per tool, see `docs/reference/{tool}.md` for the contract and
`docs/tutorials/{tool}.md` for worked examples. `uv run topo-tools
<tool> --help` lists the flags directly.

Supported input/output formats: GeoParquet, GeoPackage, Shapefile,
GeoJSON. Point any `--output-path`/`--tmp-dir`/`--debug` export somewhere
you own; never write into read-only reference data (see CLAUDE.md's Test
Datasets section for the portolan catalog's read-only rule if you're
testing against that).

## Call the API directly

```python
from topo_tools.api.dissolve import dissolve

dissolve("my_layer.gpkg", group_by=["adm2_pcode"], debug=True)
```

Each tool's `api.{tool}.{tool}()` function takes the same settings as its
CLI flags, as plain keyword arguments. `debug=True` keeps intermediate
tables around (under `tmp_dir`) for direct SQL inspection instead of
dropping them after the call, and most tools accept `step=...` to run a
single named stage.

## Run the existing automated tests

```bash
uv run pytest tests/test_<tool>.py -v
```

Each tool has its own `tests/test_{tool}.py`, generally building small
synthetic tables in DuckDB rather than depending on a fixture file, so you
can add a case there to pin down specific behavior alongside a manual run.
