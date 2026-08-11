"""Public API: close seams in an already-tiled polygon layer via coverage-clean."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import default_output_path, input_basename, resolve_input_path
from topo_tools.core.stitch import _01_inputs as inputs
from topo_tools.core.stitch import _02_clean as clean
from topo_tools.core.stitch import _03_outputs as outputs

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "clean", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "clean": ["{n}_02"],
    "outputs": [],
}


def stitch(  # noqa: PLR0913
    input_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Close seams in an already-tiled polygon layer via coverage-clean.

    Processes exactly one file per call. If output_path is omitted, it
    defaults to input_path with a "_stitched" suffix in the same directory.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = resolve_input_path(input_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(input_path, "_stitched")
    )
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    if output_path.exists() and not overwrite:
        msg = f"output already exists: {output_path}"
        raise FileExistsError(msg)
    if issues_path.exists() and not overwrite:
        msg = f"output already exists: {issues_path}"
        raise FileExistsError(msg)

    # "_stitch" keeps every table/file this call creates distinct from
    # another tool's run against the same input_path/tmp_dir.
    name = input_basename(input_path).replace(".", "_") + "_stitch"

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
            elif s == "clean":
                clean.main(conn, f"{name}_01", f"{name}_02")
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
