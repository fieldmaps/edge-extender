"""Public API: match child polygons to parent boundaries, then extend to fill gaps."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import assign_many, assign_one
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
    "clip": ["{n}_04", "{n}_04_dropped"],
    "stitch": ["{n}_05"],
    "outputs": [],
}


def _resolve_merge_columns(
    conn: DuckDBPyConnection, name: str, *, merge_columns: list[str] | bool
) -> list[str] | None:
    """Resolve True to every `{name}_parent_01` column except fid/geom."""
    if merge_columns is False:
        return None
    if merge_columns is True:
        return [
            row[0]
            for row in conn.execute(f'DESCRIBE "{name}_parent_01"').fetchall()
            if row[0] not in ("fid", "geom")
        ]
    return merge_columns


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
    merge_columns: list[str] | bool = False,
    multi_parent: bool = False,
) -> None:
    """Match children to their best-overlapping parent, then extend to fill gaps."""
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
    passthrough = bool(merge_columns)

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
        resolved_merge: list[str] | None = None
        merge_resolved = False
        for s in _STEP_ORDER:
            if step and step != s:
                continue
            if debug:
                logger.info("=== %s ===", s)
            if s == "inputs":
                inputs.main(conn, name, input_path, clip_path)
            elif s == "assign":
                if not merge_resolved:
                    resolved_merge = _resolve_merge_columns(
                        conn, name, merge_columns=merge_columns
                    )
                    merge_resolved = True
                assign_fn = assign_many if multi_parent else assign_one
                assign_fn(
                    conn,
                    name,
                    parent_match_column=parent_match_column,
                    child_match_column=child_match_column,
                    carry_columns=resolved_merge,
                )
            elif s == "groups":
                if not merge_resolved:
                    resolved_merge = _resolve_merge_columns(
                        conn, name, merge_columns=merge_columns
                    )
                    merge_resolved = True
                groups.main(
                    conn,
                    name,
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                    carry_columns=resolved_merge,
                    passthrough=passthrough,
                )
            elif s == "clip":
                clip.main(
                    conn,
                    name,
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                    passthrough=passthrough,
                )
            elif s == "stitch":
                stitch.main(conn, name, debug=debug)
            elif s == "outputs":
                outputs.main(
                    conn,
                    name,
                    output_path,
                    issues_path,
                    code_join=bool(parent_match_column and child_match_column),
                    passthrough=passthrough,
                    debug=debug,
                )
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
