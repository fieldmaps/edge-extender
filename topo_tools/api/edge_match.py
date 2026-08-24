"""Public API: match child polygons to parent boundaries, then extend to fill gaps."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.assign import assign_many
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.edge_match import _01_inputs as inputs
from topo_tools.core.edge_match import _02_groups as groups
from topo_tools.core.edge_match import _03_clip as clip
from topo_tools.core.edge_match import _04_stitch as stitch
from topo_tools.core.edge_match import _05_outputs as outputs
from topo_tools.core.io import (
    check_overwrite,
    default_output_path,
    input_basename,
    resolve_input_path,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "groups", "clip", "stitch", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    # "groups" is deliberately absent: group ids aren't known ahead of time
    # (dynamic "{n}_g{parent_fid}" names), so it falls through to the
    # "export everything currently in the connection" default below, same as
    # a full (no --step) run.
    "clip": ["{n}_04"],
    "stitch": ["{n}_05"],
    "outputs": [],
}


def match(  # noqa: C901, PLR0912, PLR0913
    input_path: str | Path,
    clip_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
    match_column: str | None = None,
    parent_match_column: str | None = None,
    child_match_column: str | None = None,
) -> None:
    """Match child polygons to their best-overlapping parent, then extend to fill gaps.

    Processes exactly one child file + one parent/clip file per call.

    match_column names one column shared by both layers to use as an exact
    code join (e.g. a pcode), winning over the spatial plurality pick where
    the two disagree; parent_match_column/child_match_column do the same
    with two differently-named columns. match_column is mutually exclusive
    with the pair. A child whose code has no match falls back to the
    spatial pick. Both outcomes are recorded as issue rows
    ('code-mismatch'/'code-fallback') alongside match's usual issues report.
    """
    if match_column is not None and (parent_match_column or child_match_column):
        msg = "match_column is mutually exclusive with parent/child_match_column"
        raise ValueError(msg)
    if bool(parent_match_column) != bool(child_match_column):
        msg = "parent_match_column and child_match_column must be given together"
        raise ValueError(msg)
    if match_column is not None:
        parent_match_column = child_match_column = match_column

    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    input_path = resolve_input_path(input_path)
    clip_path = resolve_input_path(clip_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else default_output_path(input_path, "_matched")
    )
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    check_overwrite(output_path, overwrite=overwrite)
    check_overwrite(issues_path, overwrite=overwrite)

    # "_edge_match" keeps every table/file this call creates distinct from an
    # edge_extend() run against the same input_path/tmp_dir, e.g. edge_extend's bare
    # "{name}_04" (Voronoi cells) would otherwise collide with edge_match's own
    # bare "{name}_04" (final coverage-cleaned output) if both tools shared a
    # tmp_dir and were run with --debug for side-by-side inspection.
    name = input_basename(input_path).replace(".", "_") + "_edge_match"

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
                assign_many(
                    conn,
                    name,
                    parent_match_column=parent_match_column,
                    child_match_column=child_match_column,
                )
            elif s == "groups":
                groups.main(
                    conn,
                    name,
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                )
            elif s == "clip":
                clip.main(conn, name, tmp_dir_path, threads=threads, debug=debug)
            elif s == "stitch":
                stitch.main(conn, name, debug=debug)
            elif s == "outputs":
                outputs.main(
                    conn,
                    name,
                    output_path,
                    issues_path,
                    code_join=bool(parent_match_column and child_match_column),
                    debug=debug,
                )
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
