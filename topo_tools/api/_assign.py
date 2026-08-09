"""Shared plumbing for assign-many and assign-one, which differ only by strategy."""

from logging import getLogger
from pathlib import Path
from types import ModuleType

from topo_tools.core.assign import _01_inputs as inputs
from topo_tools.core.assign import _03_outputs as outputs
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "outputs": [],
}


def run(  # noqa: C901, PLR0912, PLR0913
    children_paths: str | Path | list[str | Path],
    parent_path: str | Path,
    output_path: str | Path | None,
    issues_path: str | Path | None,
    *,
    assign_module: ModuleType,
    name_suffix: str,
    threads: int | None,
    tmp_dir: str | Path | None,
    overwrite: bool,
    debug: bool,
    step: str | None,
) -> None:
    """Run inputs -> assign_module.main -> outputs; name_suffix disambiguates tables."""
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    if isinstance(children_paths, (str, Path)):
        paths = [Path(children_paths)]
        single_path = Path(children_paths)
    else:
        paths = [Path(p) for p in children_paths]
        single_path = None

    parent_path = Path(parent_path)
    if output_path is not None:
        output_path = Path(output_path)
    elif single_path is not None:
        output_path = single_path.with_stem(single_path.stem + "_assigned")
    else:
        msg = "output_path is required when multiple children_paths are given"
        raise ValueError(msg)
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

    name = (
        single_path.name.replace(".", "_") + name_suffix
        if single_path is not None
        else output_path.name.replace(".", "_") + name_suffix
    )

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
                inputs.main(conn, name, paths, parent_path)
            elif s == "assign":
                assign_module.main(conn, name)
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
