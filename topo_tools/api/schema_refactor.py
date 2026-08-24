"""Public API: apply a (possibly human-edited) crosswalk to rename/drop columns."""

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
from topo_tools.core.schema_refactor import _01_inputs as inputs
from topo_tools.core.schema_refactor import _02_rename as rename_stage
from topo_tools.core.schema_refactor import _03_outputs as outputs

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "rename", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01", "{n}_crosswalk"],
    "rename": ["{n}_02"],
    "outputs": [],
}


def refactor(  # noqa: PLR0913
    input_path: str | Path,
    crosswalk_path: str | Path,
    output_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Rename/drop columns per a crosswalk (from map, possibly edited).

    Processes exactly one file per call. If output_path is omitted, it
    defaults to input_path with a "_mapped" suffix.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = resolve_input_path(input_path)
    crosswalk_path = Path(crosswalk_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(input_path, "_mapped")
    )
    check_overwrite(output_path, overwrite=overwrite)

    name = input_basename(input_path).replace(".", "_") + "_schema_refactor"

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
                inputs.main(conn, name, input_path, crosswalk_path)
            elif s == "rename":
                rename_stage.main(conn, name)
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
