"""Public API: close seams in an already-tiled polygon layer via coverage-clean."""

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


def stitch(  # noqa: C901, PLR0913
    input_path: str | Path | list[str | Path],
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Close seams in an already-tiled polygon layer via coverage-clean.

    input_path MAY be a list of multiple already-tiled files, combined
    internally into one layer before the clean pass; output_path is then
    required, since there's no single filename to default from. With a
    single input_path, output_path defaults to it with a "_stitched" suffix.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    if isinstance(input_path, (str, Path)):
        paths = [resolve_input_path(input_path)]
        single_path = paths[0]
    else:
        paths = [resolve_input_path(p) for p in input_path]
        single_path = None

    if output_path is not None:
        output_path = Path(output_path)
    elif single_path is not None:
        output_path = default_output_path(single_path, "_stitched")
    else:
        msg = "output_path is required when multiple input_paths are given"
        raise ValueError(msg)
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    check_overwrite(output_path, overwrite=overwrite)
    check_overwrite(issues_path, overwrite=overwrite)

    # "_stitch" keeps every table/file this call creates distinct from
    # another tool's run against the same input_path/tmp_dir.
    name = (
        input_basename(single_path).replace(".", "_") + "_stitch"
        if single_path is not None
        else output_path.name.replace(".", "_") + "_stitch"
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
                inputs.main(
                    conn, name, single_path if single_path is not None else paths
                )
            elif s == "clean":
                clean.main(conn, f"{name}_01", f"{name}_02")
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
