"""Public API: detect and fix coverage defects (gaps, overlaps) in a polygon layer."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.clean import _01_inputs as inputs
from topo_tools.core.clean import _02_issues as issues
from topo_tools.core.clean import _03_clean as clean_stage
from topo_tools.core.clean import _04_outputs as outputs
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "issues", "clean", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "issues": ["{n}_02"],
    "clean": ["{n}_03"],
    "outputs": [],
}


def _parse_maximum_gap_width(value: str) -> tuple[str, float | None]:
    if value in ("auto", "all"):
        return value, None
    try:
        return "value", float(value)
    except ValueError:
        msg = (
            f"--maximum-gap-width must be 'auto', 'all', or a number in "
            f"decimal degrees, got {value!r}"
        )
        raise ValueError(msg) from None


def _parse_snapping_distance(value: str) -> tuple[str, float | None]:
    if value == "auto":
        return "auto", None
    try:
        return "value", float(value)
    except ValueError:
        msg = (
            f"--snapping-distance must be 'auto' or a number in decimal "
            f"degrees, got {value!r}"
        )
        raise ValueError(msg) from None


def clean(  # noqa: C901, PLR0913
    input_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    maximum_gap_width: str = "auto",
    snapping_distance: str = "auto",
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Detect and fix gap/overlap defects in a single polygon layer.

    Processes exactly one file per call. Always writes two files: the
    cleaned dataset (output_path, "_cleaned" suffix if omitted) and an
    issues report (issues_path, "_issues" suffix if omitted) so a human can
    review any gaps left unfilled before deciding what to do with them.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    parsed_maximum_gap_width = _parse_maximum_gap_width(maximum_gap_width)
    parsed_snapping_distance = _parse_snapping_distance(snapping_distance)

    input_path = Path(input_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else input_path.with_stem(input_path.stem + "_cleaned")
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

    name = input_path.name.replace(".", "_") + "_clean"

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
            elif s == "clean":
                clean_stage.main(
                    conn,
                    name,
                    gap_maximum_width=parsed_maximum_gap_width,
                    snapping_distance=parsed_snapping_distance,
                )
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
