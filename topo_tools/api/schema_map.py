"""Public API: map a source-column -> target-schema crosswalk."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import (
    check_overwrite,
    default_output_path,
    input_basename,
    resolve_input_path,
)
from topo_tools.core.schema_map import _01_inputs as inputs
from topo_tools.core.schema_map import _02_map as map_stage
from topo_tools.core.schema_map import _03_outputs as outputs
from topo_tools.core.schema_map._target_schema import (
    DEFAULT_TARGET_SCHEMA_PATH,
    load_target_schema,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "map", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "map": ["{n}_02"],
    "outputs": [],
}


def map(  # noqa: A001, PLR0913
    input_path: str | Path,
    target_schema_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    layer: str | None = None,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Map a source-column -> target-schema crosswalk for one input file.

    target_schema_path defaults to the bundled generic schema.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = resolve_input_path(input_path)
    target_schema_path = (
        Path(target_schema_path)
        if target_schema_path is not None
        else DEFAULT_TARGET_SCHEMA_PATH
    )
    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(input_path, "_crosswalk").with_suffix(".csv")
    )
    check_overwrite(output_path, overwrite=overwrite)

    name = input_basename(input_path).replace(".", "_") + "_schema_map"

    with (
        resolve_tmp_dir(tmp_dir, debug=debug) as tmp_dir_path,
        pipeline_connection(
            name, tmp_dir_path, threads=threads, debug=debug, step=step
        ) as conn,
    ):
        logger.info("starting: %s", name)
        for s in _STEP_ORDER:
            if step and step != s:
                continue
            if debug:
                logger.info("=== %s ===", s)
            if s == "inputs":
                inputs.main(conn, name, input_path, layer)
            elif s == "map":
                schema = load_target_schema(target_schema_path)
                map_stage.main(conn, name, schema)
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
