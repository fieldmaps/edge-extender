"""Public API: assign each child to its parent, then clip it to that geometry."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.assign import _01_inputs as inputs
from topo_tools.core.assign import _02_one as assign_stage
from topo_tools.core.clip import _01_clip as clip_stage
from topo_tools.core.clip import _02_outputs as outputs
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "clip": ["{n}_03"],
    "outputs": [],
}


def clip(  # noqa: C901, PLR0912, PLR0913
    children_paths: str | Path | list[str | Path],
    parent_path: str | Path,
    output_paths: str | Path | list[str | Path] | None = None,
    *,
    name: str | None = None,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Assign each child to its parent via assign-one, then clip it to that geometry.

    children_paths MAY be a list, sharing a single load of parent_path;
    each children file is still its own independent assign-one group (own
    majority-vote parent). output_paths MUST then be an equal-length list,
    one destination per children file, and name MUST be given explicitly
    (there's no single path to derive one from). With a single scalar
    children_paths, output_paths defaults to children_paths with a
    "_clipped" suffix, and name defaults similarly.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    if isinstance(children_paths, (str, Path)):
        children = [Path(children_paths)]
        single_path = Path(children_paths)
    else:
        children = [Path(p) for p in children_paths]
        single_path = None

    parent_path = Path(parent_path)

    if output_paths is None:
        if single_path is None:
            msg = "output_paths is required when multiple children_paths are given"
            raise ValueError(msg)
        outputs_list = [single_path.with_stem(single_path.stem + "_clipped")]
    elif isinstance(output_paths, (str, Path)):
        outputs_list = [Path(output_paths)]
    else:
        outputs_list = [Path(p) for p in output_paths]

    if len(outputs_list) != len(children):
        msg = (
            f"output_paths must be the same length as children_paths "
            f"({len(children)}), got {len(outputs_list)}"
        )
        raise ValueError(msg)

    if name is None:
        if single_path is None:
            msg = "name is required when multiple children_paths are given"
            raise ValueError(msg)
        name = single_path.name.replace(".", "_") + "_clip"

    if step in (None, "outputs"):
        for out in outputs_list:
            if out.exists() and not overwrite:
                msg = f"output already exists: {out}"
                raise FileExistsError(msg)

    dest_by_source = {
        str(p): out for p, out in zip(children, outputs_list, strict=True)
    }

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
                inputs.main(conn, name, children, parent_path)
            elif s == "assign":
                assign_stage.main(conn, name)
            elif s == "clip":
                clip_stage.main(conn, name, tmp_dir_path, threads=threads, debug=debug)
            elif s == "outputs":
                outputs.main(conn, name, dest_by_source, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
