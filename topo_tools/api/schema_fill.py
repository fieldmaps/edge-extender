"""Public API: cascade admin-hierarchy columns down, stamp each row's real depth."""

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
from topo_tools.core.schema_fill import _01_inputs as inputs
from topo_tools.core.schema_fill import _02_fill as fill_stage
from topo_tools.core.schema_fill import _03_outputs as outputs
from topo_tools.core.schema_map._levels import detect_levels
from topo_tools.core.schema_map._target_schema import (
    DEFAULT_TARGET_SCHEMA_PATH,
    load_target_schema,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "fill", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "fill": ["{n}_02"],
    "outputs": [],
}


def fill(  # noqa: PLR0913
    input_path: str | Path,
    target_schema_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
    depth_column: str = "adm_lvl",
    cascade_from_level: int | None = None,
) -> None:
    """Cascade admin-hierarchy columns down for one input file.

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
        else default_output_path(input_path, "_fill")
    )
    check_overwrite(output_path, overwrite=overwrite)

    name = input_basename(input_path).replace(".", "_") + "_schema_fill"

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
                schema = load_target_schema(target_schema_path)
                inputs.main(conn, name, input_path, schema)
            elif s == "fill":
                schema = load_target_schema(target_schema_path)
                levels = detect_levels(conn, f"{name}_01", schema)
                if cascade_from_level is not None and cascade_from_level not in levels:
                    msg = (
                        f"cascade_from_level must be one of {levels}, "
                        f"got {cascade_from_level!r}"
                    )
                    raise ValueError(msg)
                fill_stage.main(
                    conn,
                    f"{name}_01",
                    f"{name}_02",
                    levels=levels,
                    schema=schema,
                    depth_column=depth_column,
                    cascade_from_level=cascade_from_level,
                )
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
