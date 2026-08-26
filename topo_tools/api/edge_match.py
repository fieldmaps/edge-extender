"""Public API: match child polygons to parent boundaries, then extend to fill gaps."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import (
    assign_many,
    assign_one,
    child_bbox_extent,
    fill_unmatched_parents,
    load_parent,
    prepare_parent_tiles,
    resolve_merge_columns,
    validate_merge_flags,
)
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
    "inputs": ["{n}_child_01", "{n}_parent_01", "{n}_parent_full"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    # "groups" is absent: group ids aren't known ahead of time (dynamic
    # "{n}_g{parent_fid}" names), so it falls through to the default below.
    "clip": ["{n}_04", "{n}_04_dropped", "{n}_02_gap_fill"],
    "stitch": ["{n}_05"],
    "outputs": [],
}


def match(  # noqa: C901, PLR0912, PLR0913, PLR0915
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
    merge: bool = False,
    parent_include: list[str] | None = None,
    parent_exclude: list[str] | None = None,
    child_include: list[str] | None = None,
    child_exclude: list[str] | None = None,
    prefer: str | None = None,
    multi_parent: bool = False,
) -> None:
    """Match one or more children layers to their best-overlapping parent."""
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
    validate_merge_flags(
        merge=merge,
        parent_include=parent_include,
        parent_exclude=parent_exclude,
        child_include=child_include,
        child_exclude=child_exclude,
        prefer=prefer,
    )
    passthrough = merge

    if isinstance(input_paths, (str, Path)):
        paths = [resolve_input_path(input_paths)]
        single_path = paths[0]
    else:
        paths = [resolve_input_path(p) for p in input_paths]
        single_path = None

    if single_path is None and step is not None:
        msg = "step is not supported when multiple input_paths are given"
        raise ValueError(msg)
    if single_path is None and multi_parent:
        msg = "multi_parent is not supported when multiple input_paths are given"
        raise ValueError(msg)

    clip_path = resolve_input_path(clip_path)
    if output_path is not None:
        output_path = Path(output_path)
    elif single_path is not None:
        output_path = default_output_path(single_path, "_matched")
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

    # "_edge_match" keeps this call's tables/files distinct from an
    # edge_extend() run sharing the same input_path/tmp_dir.
    name = (
        input_basename(single_path).replace(".", "_") + "_edge_match"
        if single_path is not None
        else output_path.name.replace(".", "_") + "_edge_match"
    )

    with (
        resolve_tmp_dir(tmp_dir, debug=debug) as tmp_dir_path,
        pipeline_connection(
            name, tmp_dir_path, threads=threads, debug=debug, step=step
        ) as conn,
    ):
        logger.info("starting: %s", name)
        if single_path is None:
            _match_multi_file(
                conn,
                name,
                paths,
                clip_path,
                output_path,
                issues_path,
                tmp_dir_path,
                threads=threads,
                debug=debug,
                parent_match_column=parent_match_column,
                child_match_column=child_match_column,
                merge=merge,
                parent_include=parent_include,
                parent_exclude=parent_exclude,
                child_include=child_include,
                child_exclude=child_exclude,
                prefer=prefer,
            )
        else:
            resolved_parent_columns: list[str] | None = None
            resolved_child_columns: list[str] | None = None
            merge_resolved = False
            for s in _STEP_ORDER:
                if step and step != s:
                    continue
                if debug:
                    logger.info("=== %s ===", s)
                if s == "inputs":
                    inputs.main(conn, name, single_path, clip_path)
                    if passthrough:
                        conn.execute(f"""--sql
                            CREATE OR REPLACE TABLE "{name}_parent_full" AS
                            SELECT * FROM "{name}_parent_01"
                        """)
                elif s == "assign":
                    if not merge_resolved:
                        resolved_parent_columns, resolved_child_columns = (
                            resolve_merge_columns(
                                conn,
                                name,
                                merge=merge,
                                parent_include=parent_include,
                                parent_exclude=parent_exclude,
                                child_include=child_include,
                                child_exclude=child_exclude,
                                prefer=prefer,
                            )
                        )
                        merge_resolved = True
                    assign_fn = assign_many if multi_parent else assign_one
                    assign_fn(
                        conn,
                        name,
                        parent_match_column=parent_match_column,
                        child_match_column=child_match_column,
                        carry_columns=resolved_parent_columns,
                        child_columns=resolved_child_columns,
                    )
                elif s == "groups":
                    if not merge_resolved:
                        resolved_parent_columns, resolved_child_columns = (
                            resolve_merge_columns(
                                conn,
                                name,
                                merge=merge,
                                parent_include=parent_include,
                                parent_exclude=parent_exclude,
                                child_include=child_include,
                                child_exclude=child_exclude,
                                prefer=prefer,
                            )
                        )
                        merge_resolved = True
                    groups.main(
                        conn,
                        name,
                        tmp_dir_path,
                        threads=threads,
                        debug=debug,
                        carry_columns=resolved_parent_columns,
                        child_columns=resolved_child_columns,
                        passthrough=passthrough,
                    )
                elif s == "clip":
                    if not merge_resolved:
                        resolved_parent_columns, resolved_child_columns = (
                            resolve_merge_columns(
                                conn,
                                name,
                                merge=merge,
                                parent_include=parent_include,
                                parent_exclude=parent_exclude,
                                child_include=child_include,
                                child_exclude=child_exclude,
                                prefer=prefer,
                            )
                        )
                        merge_resolved = True
                    clip.main(
                        conn,
                        name,
                        tmp_dir_path,
                        threads=threads,
                        debug=debug,
                        passthrough=passthrough,
                    )
                    if passthrough:
                        fill_unmatched_parents(
                            conn,
                            name,
                            carry_columns=resolved_parent_columns,
                            result_table=f"{name}_04",
                            parent_snapshot_table=f"{name}_parent_full",
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
                        fill_gaps=passthrough,
                        debug=debug,
                    )
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)


def _union_bbox(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Combine two (xmin, ymin, xmax, ymax) bboxes into their enclosing bbox."""
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _fold(
    conn: DuckDBPyConnection, acc_table: str, iter_table: str, *, seeded: bool
) -> None:
    """Fold iter_table into acc_table (seed on first call, UNION ALL BY NAME after)."""
    if not seeded:
        conn.execute(f'CREATE TABLE "{acc_table}" AS SELECT * FROM "{iter_table}"')
    else:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{acc_table}" AS
            SELECT * FROM "{acc_table}"
            UNION ALL BY NAME
            SELECT * FROM "{iter_table}"
        """)


def _match_multi_file(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    paths: list[Path],
    clip_path: Path | str,
    output_path: Path,
    issues_path: Path,
    tmp_dir_path: Path,
    *,
    threads: int | None,
    debug: bool,
    parent_match_column: str | None,
    child_match_column: str | None,
    merge: bool,
    parent_include: list[str] | None,
    parent_exclude: list[str] | None,
    child_include: list[str] | None,
    child_exclude: list[str] | None,
    prefer: str | None,
) -> None:
    """Load/assign one children file at a time, sharing one already-loaded parent.

    Groups/clip/stitch/outputs run once over the fully accumulated result
    afterward, so cross-file children sharing a parent_fid extend together.
    """
    load_parent(conn, name, clip_path)
    conn.execute(f"""--sql
        CREATE TABLE "{name}_parent_full" AS SELECT * FROM "{name}_parent_01"
    """)

    combined_bbox: tuple[float, float, float, float] | None = None
    resolved_parent_columns: list[str] | None = None
    resolved_child_columns: list[str] | None = None
    for i, child_path in enumerate(paths):
        inputs.load_and_clean_child(conn, name, child_path)
        if i == 0:
            resolved_parent_columns, resolved_child_columns = resolve_merge_columns(
                conn,
                name,
                merge=merge,
                parent_include=parent_include,
                parent_exclude=parent_exclude,
                child_include=child_include,
                child_exclude=child_exclude,
                prefer=prefer,
            )
        bbox = child_bbox_extent(conn, name)
        if bbox is not None:
            combined_bbox = (
                bbox if combined_bbox is None else _union_bbox(combined_bbox, bbox)
            )
        conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
    prepare_parent_tiles(conn, name, child_bbox=combined_bbox)

    passthrough = merge

    acc_child = f"{name}_child_01_acc"
    acc_assign = f"{name}_02_assign_acc"
    acc_unassigned = f"{name}_02_unassigned_acc"
    for tbl in (acc_child, acc_assign, acc_unassigned):
        conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')

    fid_offset = 0
    for i, child_path in enumerate(paths):
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_parent_01" AS
            SELECT * FROM "{name}_parent_full"
        """)
        inputs.load_and_clean_child(conn, name, child_path)
        conn.execute(f'UPDATE "{name}_child_01" SET fid = fid + {fid_offset}')
        assign_one(
            conn,
            name,
            use_cached_tiles=True,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
            carry_columns=resolved_parent_columns,
            child_columns=resolved_child_columns,
        )

        seeded = i > 0
        _fold(conn, acc_child, f"{name}_child_01", seeded=seeded)
        _fold(conn, acc_assign, f"{name}_02_assign", seeded=seeded)
        _fold(conn, acc_unassigned, f"{name}_02_unassigned", seeded=seeded)

        new_max = conn.execute(f'SELECT MAX(fid) FROM "{name}_child_01"').fetchone()[0]
        fid_offset = new_max if new_max is not None else fid_offset

    for acc, canonical in (
        (acc_child, f"{name}_child_01"),
        (acc_assign, f"{name}_02_assign"),
        (acc_unassigned, f"{name}_02_unassigned"),
    ):
        conn.execute(f'DROP TABLE IF EXISTS "{canonical}"')
        conn.execute(f'ALTER TABLE "{acc}" RENAME TO "{canonical}"')

    # groups/clip need every matched parent fid, not just the last file's
    # narrowed set (assign_one narrows {name}_parent_01 every iteration).
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_parent_01" AS
        SELECT * FROM "{name}_parent_full"
    """)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_parts"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_tiles"')

    groups.main(
        conn,
        name,
        tmp_dir_path,
        threads=threads,
        debug=debug,
        carry_columns=resolved_parent_columns,
        child_columns=resolved_child_columns,
        passthrough=passthrough,
    )
    clip.main(
        conn, name, tmp_dir_path, threads=threads, debug=debug, passthrough=passthrough
    )
    if passthrough:
        fill_unmatched_parents(
            conn,
            name,
            carry_columns=resolved_parent_columns,
            result_table=f"{name}_04",
            parent_snapshot_table=f"{name}_parent_full",
        )
    stitch.main(conn, name, debug=debug)
    outputs.main(
        conn,
        name,
        output_path,
        issues_path,
        code_join=bool(parent_match_column and child_match_column),
        passthrough=passthrough,
        fill_gaps=passthrough,
        debug=debug,
    )

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_full"')
