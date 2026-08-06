"""Public API: match child polygons to parent boundaries, then extend to fill gaps."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.match import _01_inputs as inputs
from topo_tools.core.match import _02_assign as assign
from topo_tools.core.match import _03_groups as groups
from topo_tools.core.match import _04_merge as merge
from topo_tools.core.match import _05_outputs as outputs

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "groups", "merge", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    # "groups" is deliberately absent: group ids aren't known ahead of time
    # (dynamic "{n}_g{parent_fid}" names), so it falls through to the
    # "export everything currently in the connection" default below, same as
    # a full (no --step) run.
    "merge": ["{n}_04"],
    "outputs": [],
}


def match(  # noqa: C901, PLR0913
    input_path: str | Path,
    clip_path: str | Path,
    output_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Match child polygons to their best-overlapping parent, then extend to fill gaps.

    Processes exactly one child file + one parent/clip file per call. Children
    are assigned to whichever parent polygon they share the largest area with,
    grouped by that assignment, extended within each group independently (in
    an isolated subprocess per group), clipped to that group's own parent,
    reassembled, and coverage-cleaned once as a whole. If output_path is
    omitted, it defaults to input_path with a "_matched" suffix in the same
    directory.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = Path(input_path)
    clip_path = Path(clip_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else input_path.with_stem(input_path.stem + "_matched")
    )
    if output_path.exists() and not overwrite:
        msg = f"output already exists: {output_path}"
        raise FileExistsError(msg)

    # "_match" keeps every table/file this call creates distinct from an
    # extend() run against the same input_path/tmp_dir -- e.g. extend's bare
    # "{name}_04" (Voronoi cells) would otherwise collide with match's own
    # bare "{name}_04" (final coverage-cleaned output) if both tools shared a
    # tmp_dir and were run with --debug for side-by-side inspection.
    name = input_path.name.replace(".", "_") + "_match"

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
                inputs.main(conn, name, input_path, clip_path)
            elif s == "assign":
                assign.main(conn, name)
            elif s == "groups":
                groups.main(
                    conn,
                    name,
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                )
            elif s == "merge":
                merge.main(conn, name, debug=debug)
            elif s == "outputs":
                outputs.main(conn, name, output_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
