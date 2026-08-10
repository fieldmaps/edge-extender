"""Public API: scan a single polygon layer for gap/overlap coverage defects."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.detect import _01_inputs as inputs
from topo_tools.core.detect import _02_issues as issues
from topo_tools.core.detect import _03_outputs as outputs
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "issues", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "issues": ["{n}_02"],
    "outputs": [],
}


def detect(  # noqa: PLR0913
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Scan a single polygon layer for gap/overlap coverage defects.

    Processes exactly one file per call. If output_path is omitted, it
    defaults to input_path with an "_issues" suffix in the same directory.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = Path(input_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else input_path.with_stem(input_path.stem + "_issues")
    )
    if output_path.exists() and not overwrite:
        msg = f"output already exists: {output_path}"
        raise FileExistsError(msg)

    # "_detect" keeps every table/file this call creates distinct from
    # another tool's run against the same input_path/tmp_dir.
    name = input_path.name.replace(".", "_") + "_detect"

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
            elif s == "issues":
                issues.main(conn, name, debug=debug)
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
