"""Public API: assign each child to its parent, then clip it to that geometry."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import (
    assign_one,
    load_children,
    load_parent,
    prepare_parent_tiles,
)
from topo_tools.core.clip import _01_clip as clip_stage
from topo_tools.core.clip import _02_outputs as outputs
from topo_tools.core.coverage import assign_issue_rows_sql
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import (
    check_overwrite,
    default_output_path,
    export_geometry_table,
    export_issues_table,
    input_basename,
    resolve_input_path,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "clip": ["{n}_03"],
    "outputs": [],
}

_PER_FILE_TABLES = ("_child_01", "_02_pairs", "_02_assign", "_02_unassigned", "_03")


def clip(  # noqa: C901, PLR0912, PLR0913, PLR0915
    children_paths: str | Path | list[str | Path],
    parent_path: str | Path,
    output_paths: str | Path | list[str | Path] | None = None,
    issues_paths: str | Path | list[str | Path] | None = None,
    *,
    name: str | None = None,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
    match_column: str | None = None,
    parent_match_column: str | None = None,
    child_match_column: str | None = None,
) -> None:
    """Assign each child to its parent via assign-one, then clip it to that geometry.

    children_paths MAY be a list, sharing a single load of parent_path;
    each children file is still its own independent assign-one group (own
    majority-vote parent), processed one file at a time so only one file's
    geometry is ever resident alongside the shared parent. output_paths MUST
    then be an equal-length list, one destination per children file, and
    name MUST be given explicitly (there's no single path to derive one
    from); step MUST be None in this case (no per-step resumability for the
    multi-file loop). With a single scalar children_paths, output_paths
    defaults to children_paths with a "_clipped" suffix, name defaults
    similarly, and step works as usual.

    match_column names one column shared by both layers to use as an exact
    code join (e.g. a pcode), winning over the spatial file-vote pick where
    the two disagree; parent_match_column/child_match_column do the same
    with two differently-named columns. match_column is mutually exclusive
    with the pair. A file with no code matches at all falls back to the
    spatial pick. Both outcomes are recorded as issue rows
    ('code-mismatch'/'code-fallback') in a per-children-file issues report,
    clip's only issue kind since it has no topology hard gate of its own.
    issues_paths (same shape as output_paths) is only used when a match
    column is given; it MUST then be the same length as output_paths in the
    multi-file case, and defaults to each output path with an "_issues"
    suffix when omitted.
    """
    if match_column is not None and (parent_match_column or child_match_column):
        msg = "match_column is mutually exclusive with parent/child_match_column"
        raise ValueError(msg)
    if bool(parent_match_column) != bool(child_match_column):
        msg = "parent_match_column and child_match_column must be given together"
        raise ValueError(msg)
    if match_column is not None:
        parent_match_column = child_match_column = match_column
    code_join = bool(parent_match_column and child_match_column)

    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)

    if isinstance(children_paths, (str, Path)):
        children = [resolve_input_path(children_paths)]
        single_path = resolve_input_path(children_paths)
    else:
        children = [resolve_input_path(p) for p in children_paths]
        single_path = None

    if single_path is None and step is not None:
        msg = "step is not supported when multiple children_paths are given"
        raise ValueError(msg)

    parent_path = resolve_input_path(parent_path)

    if output_paths is None:
        if single_path is None:
            msg = "output_paths is required when multiple children_paths are given"
            raise ValueError(msg)
        outputs_list = [default_output_path(single_path, "_clipped")]
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
        name = input_basename(single_path).replace(".", "_") + "_clip"

    issues_list: list[Path] = []
    if code_join:
        if issues_paths is None:
            issues_list = [o.with_stem(o.stem + "_issues") for o in outputs_list]
        elif isinstance(issues_paths, (str, Path)):
            issues_list = [Path(issues_paths)]
        else:
            issues_list = [Path(p) for p in issues_paths]
        if len(issues_list) != len(outputs_list):
            msg = (
                f"issues_paths must be the same length as output_paths "
                f"({len(outputs_list)}), got {len(issues_list)}"
            )
            raise ValueError(msg)

    if step in (None, "outputs"):
        for out in outputs_list:
            check_overwrite(out, overwrite=overwrite)
        for issues_out in issues_list:
            check_overwrite(issues_out, overwrite=overwrite)

    with (
        resolve_tmp_dir(tmp_dir, debug=debug) as tmp_dir_path,
        pipeline_connection(
            name, tmp_dir_path, threads=threads, debug=debug, step=step
        ) as conn,
    ):
        logger.info("starting: %s", name)
        if single_path is None:
            _clip_each_file(
                conn,
                name,
                children,
                parent_path,
                outputs_list,
                issues_list,
                tmp_dir_path,
                threads=threads,
                debug=debug,
                parent_match_column=parent_match_column,
                child_match_column=child_match_column,
            )
        else:
            _clip_single_file(
                conn,
                name,
                children,
                parent_path,
                outputs_list[0],
                issues_list[0] if issues_list else None,
                tmp_dir_path,
                threads=threads,
                debug=debug,
                step=step,
                parent_match_column=parent_match_column,
                child_match_column=child_match_column,
            )
        logger.info("done: %s", name)


def _clip_single_file(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    children: list[Path | str],
    parent_path: Path | str,
    output_path: Path,
    issues_path: Path | None,
    tmp_dir_path: Path,
    *,
    threads: int | None,
    debug: bool,
    step: str | None,
    parent_match_column: str | None,
    child_match_column: str | None,
) -> None:
    """Run clip's four named stages once, in order, over one children file."""
    dest_by_source = {str(children[0]): output_path}
    issues_dest_by_source = {str(children[0]): issues_path} if issues_path else None
    code_join = bool(parent_match_column and child_match_column)
    for s in _STEP_ORDER:
        if step and step != s:
            continue
        if debug:
            logger.info("=== %s ===", s)
        if s == "inputs":
            load_children(conn, name, children)
            load_parent(conn, name, parent_path)
        elif s == "assign":
            assign_one(
                conn,
                name,
                parent_match_column=parent_match_column,
                child_match_column=child_match_column,
            )
        elif s == "clip":
            clip_stage.main(conn, name, tmp_dir_path, threads=threads, debug=debug)
        elif s == "outputs":
            outputs.main(
                conn,
                name,
                dest_by_source,
                issues_dest_by_source,
                code_join=code_join,
                debug=debug,
            )
    maybe_export_debug_tables(conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug)


def _clip_each_file(  # noqa: C901, PLR0912, PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    children: list[Path | str],
    parent_path: Path | str,
    outputs_list: list[Path],
    issues_list: list[Path],
    tmp_dir_path: Path,
    *,
    threads: int | None,
    debug: bool,
    parent_match_column: str | None,
    child_match_column: str | None,
) -> None:
    """Clip one children file at a time, sharing one already-loaded parent.

    Keeps only one file's geometry resident alongside the shared parent at a
    time, instead of unioning every children file into one table first.
    """
    load_parent(conn, name, parent_path)
    conn.execute(f"""--sql
        CREATE TABLE "{name}_parent_full" AS SELECT * FROM "{name}_parent_01"
    """)
    prepare_parent_tiles(conn, name)

    code_join = bool(parent_match_column and child_match_column)
    staged: list[tuple[Path, Path]] = []
    staged_issues: list[tuple[Path, Path]] = []
    failed: list[str] = []
    for child_path, dest, issues_dest in zip(
        children, outputs_list, issues_list or [None] * len(children), strict=True
    ):
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_parent_01" AS
            SELECT * FROM "{name}_parent_full"
        """)
        load_children(conn, name, [child_path])
        assign_one(
            conn,
            name,
            use_cached_tiles=True,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
        )
        clip_stage.main(conn, name, tmp_dir_path, threads=threads, debug=debug)

        count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
        if count == 0:
            failed.append(str(child_path))
        else:
            tmp_path = dest.parent / f".tmp_{dest.name}"
            conn.execute(f"""--sql
                CREATE OR REPLACE TEMP VIEW "{name}_03_one" AS
                SELECT * EXCLUDE (source_file) FROM "{name}_03"
            """)
            export_geometry_table(conn, f"{name}_03_one", tmp_path)
            staged.append((tmp_path, dest))

            if code_join and issues_dest is not None:
                issues_tmp_path = issues_dest.parent / f".tmp_{issues_dest.name}"
                conn.execute(f"""--sql
                    CREATE OR REPLACE TABLE "{name}_02_issues" AS
                    {assign_issue_rows_sql(name, source_file_expr="c.source_file")}
                """)
                export_issues_table(conn, f"{name}_02_issues", issues_tmp_path)
                if issues_tmp_path.exists():
                    staged_issues.append((issues_tmp_path, issues_dest))

        if not debug:
            conn.execute(f'DROP VIEW IF EXISTS "{name}_03_one"')
            conn.execute(f'DROP TABLE IF EXISTS "{name}_02_issues"')
            for tbl in _PER_FILE_TABLES:
                conn.execute(f'DROP TABLE IF EXISTS "{name}{tbl}"')

    if failed:
        for tmp_path, _ in staged:
            tmp_path.unlink(missing_ok=True)
        for issues_tmp_path, _ in staged_issues:
            issues_tmp_path.unlink(missing_ok=True)
        msg = f"clip: no child survived clipping for: {failed}"
        raise RuntimeError(msg)

    for tmp_path, dest in staged:
        tmp_path.replace(dest)
    for issues_tmp_path, issues_dest in staged_issues:
        issues_tmp_path.replace(issues_dest)
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_full"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_parts"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_tiles"')
