"""Public API: aggregate a polygon layer into a coarser one by grouping on columns."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.dissolve import _01_inputs as inputs
from topo_tools.core.dissolve import _02_dissolve as dissolve_stage
from topo_tools.core.dissolve import _03_outputs as outputs
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

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "dissolve", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_01"],
    "dissolve": ["{n}_02"],
    "outputs": [],
}


def dissolve(  # noqa: PLR0913
    input_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    group_by: list[str],
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Aggregate a polygon layer into a coarser one, grouping on `group_by` columns.

    A NULL value in a `group_by` column forms its own group like any other
    value, matching GDAL's `combine --group-by`. Every other column is kept
    via any_value if it's actually constant within every group, dropped
    (with a warning) if not.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)
    if not group_by:
        msg = "group_by must be a non-empty list of column names"
        raise ValueError(msg)

    single_path = resolve_input_path(input_path)

    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(single_path, "_dissolved")
    )
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    check_overwrite(output_path, overwrite=overwrite)
    check_overwrite(issues_path, overwrite=overwrite)

    # "_dissolve" keeps every table/file this call creates distinct from
    # another tool's run against the same input_path/tmp_dir.
    name = input_basename(single_path).replace(".", "_") + "_dissolve"

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
                inputs.main(conn, name, single_path, group_by=group_by)
            elif s == "dissolve":
                dissolve_stage.main(conn, f"{name}_01", f"{name}_02", group_by=group_by)
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
