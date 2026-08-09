"""Public API: fit already-extended children into a new parent/clip layer."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.assign import _01_inputs as inputs
from topo_tools.core.assign import _02_one as assign
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.mosaic import _01_clip as clip
from topo_tools.core.mosaic import _02_stitch as stitch
from topo_tools.core.mosaic import _03_outputs as outputs

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "stitch", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "clip": ["{n}_03"],
    "stitch": ["{n}_04"],
    "outputs": [],
}


def mosaic(  # noqa: C901, PLR0912, PLR0913
    input_paths: str | Path | list[str | Path],
    clip_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Fit one or more already-extended children layers into a new parent/clip layer.

    input_paths MAY be a list; output_path is then required, since there's
    no single filename to default from.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    if isinstance(input_paths, (str, Path)):
        paths = [Path(input_paths)]
        single_path = Path(input_paths)
    else:
        paths = [Path(p) for p in input_paths]
        single_path = None

    clip_path = Path(clip_path)
    if output_path is not None:
        output_path = Path(output_path)
    elif single_path is not None:
        output_path = single_path.with_stem(single_path.stem + "_mosaicked")
    else:
        msg = "output_path is required when multiple input_paths are given"
        raise ValueError(msg)
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    if step in (None, "outputs"):
        if output_path.exists() and not overwrite:
            msg = f"output already exists: {output_path}"
            raise FileExistsError(msg)
        if issues_path.exists() and not overwrite:
            msg = f"output already exists: {issues_path}"
            raise FileExistsError(msg)

    # "_mosaic" keeps every table/file this call creates distinct from an
    # extend()/match() run against the same input_path/tmp_dir.
    name = (
        single_path.name.replace(".", "_") + "_mosaic"
        if single_path is not None
        else output_path.name.replace(".", "_") + "_mosaic"
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
                inputs.main(conn, name, paths, clip_path)
            elif s == "assign":
                assign.main(conn, name)
            elif s == "clip":
                clip.main(conn, name, tmp_dir_path, threads=threads, debug=debug)
            elif s == "stitch":
                stitch.main(conn, name, debug=debug)
            elif s == "outputs":
                outputs.main(conn, name, output_path, issues_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
