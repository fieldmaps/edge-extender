"""Public API: assign each child to its parent, then clip it to that geometry."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.clip import _01_inputs as inputs
from topo_tools.core.clip import _02_assign as assign_stage
from topo_tools.core.clip import _03_clip as clip_stage
from topo_tools.core.clip import _04_outputs as outputs
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_clip_in"],
    "clip": ["{n}_03"],
    "outputs": [],
}


def clip(  # noqa: PLR0913
    children_path: str | Path,
    parent_path: str | Path,
    output_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Assign each child to its parent via assign-one, then clip it to that geometry.

    Processes exactly one file per call; if output_path is omitted, it
    defaults to children_path with a "_clipped" suffix.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    children_path = Path(children_path)
    parent_path = Path(parent_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else children_path.with_stem(children_path.stem + "_clipped")
    )
    if output_path.exists() and not overwrite:
        msg = f"output already exists: {output_path}"
        raise FileExistsError(msg)

    name = children_path.name.replace(".", "_") + "_clip"

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
                inputs.main(conn, name, children_path, parent_path)
            elif s == "assign":
                assign_stage.main(conn, name, children_path)
            elif s == "clip":
                clip_stage.main(
                    conn,
                    f"{name}_02_clip_in",
                    f'"{name}_parent_01"',
                    f"{name}_03",
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                )
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
