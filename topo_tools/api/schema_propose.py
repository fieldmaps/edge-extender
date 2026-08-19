"""Public API: propose a source-column -> target-schema crosswalk."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import default_output_path, input_basename, resolve_input_path
from topo_tools.core.schema_propose import _01_inputs as inputs
from topo_tools.core.schema_propose import _02_propose as propose_stage
from topo_tools.core.schema_propose import _03_outputs as outputs
from topo_tools.core.schema_propose._target_schema import load_target_schema

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "propose", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "propose": ["{n}_02"],
    "outputs": [],
}


def schema_propose(  # noqa: PLR0913
    input_path: str | Path,
    target_schema_path: str | Path,
    output_path: str | Path | None = None,
    *,
    own_level: int | None = None,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Propose a source-column -> target-schema crosswalk for one input file.

    Never renames anything itself, only proposes (see schema_apply for
    that). Processes exactly one file per call. If output_path is omitted,
    it defaults to input_path with a "_crosswalk.json" name.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)
    if own_level is not None and own_level < 0:
        msg = f"own_level must be non-negative, got {own_level}"
        raise ValueError(msg)

    input_path = resolve_input_path(input_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(input_path, "_crosswalk").with_suffix(".json")
    )
    if output_path.exists() and not overwrite:
        msg = f"output already exists: {output_path}"
        raise FileExistsError(msg)

    name = input_basename(input_path).replace(".", "_") + "_schema_propose"

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
                inputs.main(conn, name, input_path)
            elif s == "propose":
                fields = load_target_schema(target_schema_path)
                propose_stage.main(conn, name, fields, own_level=own_level)
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
