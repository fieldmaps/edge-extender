"""Public API: fit already-extended children into a new parent/clip layer."""

from logging import getLogger
from pathlib import Path

from topo_tools.core.assign import assign_one, load_children, load_parent
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.edge_mosaic import _01_clip as clip
from topo_tools.core.edge_mosaic import _02_stitch as stitch
from topo_tools.core.edge_mosaic import _03_outputs as outputs
from topo_tools.core.io import (
    check_overwrite,
    default_output_path,
    input_basename,
    resolve_input_path,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "stitch", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "clip": ["{n}_03", "{n}_02_passthrough"],
    "stitch": ["{n}_04"],
    "outputs": [],
}

_ON_UNMATCHED_CHOICES = ("drop", "passthrough")


def mosaic(  # noqa: C901, PLR0912, PLR0913, PLR0915
    input_paths: str | Path | list[str | Path],
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
    carry_columns: list[str] | None = None,
    on_unmatched: str = "drop",
) -> None:
    """Fit one or more already-extended children layers into a new parent/clip layer."""
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
    if on_unmatched not in _ON_UNMATCHED_CHOICES:
        msg = (
            f"on_unmatched must be one of {_ON_UNMATCHED_CHOICES}, got {on_unmatched!r}"
        )
        raise ValueError(msg)
    passthrough = on_unmatched == "passthrough"

    if isinstance(input_paths, (str, Path)):
        paths = [resolve_input_path(input_paths)]
        single_path = resolve_input_path(input_paths)
    else:
        paths = [resolve_input_path(p) for p in input_paths]
        single_path = None

    clip_path = resolve_input_path(clip_path)
    if output_path is not None:
        output_path = Path(output_path)
    elif single_path is not None:
        output_path = default_output_path(single_path, "_mosaicked")
    else:
        msg = "output_path is required when multiple input_paths are given"
        raise ValueError(msg)
    issues_path = (
        Path(issues_path)
        if issues_path is not None
        else output_path.with_stem(output_path.stem + "_issues")
    )
    if step in (None, "outputs"):
        check_overwrite(output_path, overwrite=overwrite)
        check_overwrite(issues_path, overwrite=overwrite)

    # "_edge_mosaic" keeps every table/file this call creates distinct from an
    # edge_extend()/edge_match() run against the same input_path/tmp_dir.
    name = (
        input_basename(single_path).replace(".", "_") + "_edge_mosaic"
        if single_path is not None
        else output_path.name.replace(".", "_") + "_edge_mosaic"
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
                load_children(conn, name, paths)
                load_parent(conn, name, clip_path)
            elif s == "assign":
                assign_one(
                    conn,
                    name,
                    parent_match_column=parent_match_column,
                    child_match_column=child_match_column,
                    carry_columns=carry_columns,
                )
            elif s == "clip":
                clip.main(
                    conn,
                    name,
                    tmp_dir_path,
                    threads=threads,
                    debug=debug,
                    carry_columns=carry_columns,
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
