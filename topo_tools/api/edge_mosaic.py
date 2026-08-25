"""Public API: fit already-extended children into a new parent/clip layer."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.assign import (
    assign_one,
    load_children,
    load_parent,
    prepare_parent_tiles,
)
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
    merge_columns: list[str] | bool = False,
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
    passthrough = bool(merge_columns)

    if isinstance(input_paths, (str, Path)):
        paths = [resolve_input_path(input_paths)]
        single_path = resolve_input_path(input_paths)
    else:
        paths = [resolve_input_path(p) for p in input_paths]
        single_path = None

    if single_path is None and step is not None:
        msg = "step is not supported when multiple input_paths are given"
        raise ValueError(msg)

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
        if single_path is None:
            _mosaic_multi_file(
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
                merge_columns=merge_columns,
            )
        else:
            resolved_merge: list[str] | None = None
            merge_resolved = False
            for s in _STEP_ORDER:
                if step and step != s:
                    continue
                if debug:
                    logger.info("=== %s ===", s)
                if s == "inputs":
                    load_children(conn, name, paths)
                    load_parent(conn, name, clip_path)
                elif s == "assign":
                    if not merge_resolved:
                        resolved_merge = _resolve_merge_columns(
                            conn, name, merge_columns=merge_columns
                        )
                        merge_resolved = True
                    assign_one(
                        conn,
                        name,
                        parent_match_column=parent_match_column,
                        child_match_column=child_match_column,
                        carry_columns=resolved_merge,
                    )
                elif s == "clip":
                    if not merge_resolved:
                        resolved_merge = _resolve_merge_columns(
                            conn, name, merge_columns=merge_columns
                        )
                        merge_resolved = True
                    clip.main(
                        conn,
                        name,
                        tmp_dir_path,
                        threads=threads,
                        debug=debug,
                        carry_columns=resolved_merge,
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


def _mosaic_multi_file(  # noqa: PLR0913, PLR0917
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
    merge_columns: list[str] | bool,
) -> None:
    """Assign/clip one children file at a time, sharing one already-loaded parent."""
    load_parent(conn, name, clip_path)
    conn.execute(f"""--sql
        CREATE TABLE "{name}_parent_full" AS SELECT * FROM "{name}_parent_01"
    """)
    prepare_parent_tiles(conn, name)

    resolved_merge = _resolve_merge_columns(conn, name, merge_columns=merge_columns)
    passthrough = bool(merge_columns)

    acc_child = f"{name}_child_01_acc"
    acc_assign = f"{name}_02_assign_acc"
    acc_unassigned = f"{name}_02_unassigned_acc"
    acc_passthrough = f"{name}_02_passthrough_acc"
    for tbl in (acc_child, acc_assign, acc_unassigned, acc_passthrough, f"{name}_03"):
        conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')

    fid_offset = 0
    for i, child_path in enumerate(paths):
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_parent_01" AS
            SELECT * FROM "{name}_parent_full"
        """)
        load_children(conn, name, [child_path])
        conn.execute(f'UPDATE "{name}_child_01" SET fid = fid + {fid_offset}')
        assign_one(
            conn,
            name,
            use_cached_tiles=True,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
            carry_columns=resolved_merge,
        )
        clip.main(
            conn,
            name,
            tmp_dir_path,
            threads=threads,
            debug=debug,
            carry_columns=resolved_merge,
            passthrough=passthrough,
            result_table=f"{name}_03_iter",
            raise_if_empty=False,
        )

        seeded = i > 0
        _fold(conn, f"{name}_03", f"{name}_03_iter", seeded=seeded)
        _fold(conn, acc_child, f"{name}_child_01", seeded=seeded)
        _fold(conn, acc_assign, f"{name}_02_assign", seeded=seeded)
        _fold(conn, acc_unassigned, f"{name}_02_unassigned", seeded=seeded)
        if passthrough:
            _fold(conn, acc_passthrough, f"{name}_02_passthrough", seeded=seeded)

        new_max = conn.execute(f'SELECT MAX(fid) FROM "{name}_child_01"').fetchone()[0]
        fid_offset = new_max if new_max is not None else fid_offset
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03_iter"')

    conn.execute(f'DROP TABLE IF EXISTS "{name}_child_01"')
    conn.execute(f'ALTER TABLE "{acc_child}" RENAME TO "{name}_child_01"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_assign"')
    conn.execute(f'ALTER TABLE "{acc_assign}" RENAME TO "{name}_02_assign"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_unassigned"')
    conn.execute(f'ALTER TABLE "{acc_unassigned}" RENAME TO "{name}_02_unassigned"')
    if passthrough:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_passthrough"')
        conn.execute(
            f'ALTER TABLE "{acc_passthrough}" RENAME TO "{name}_02_passthrough"'
        )

    count = conn.execute(f'SELECT COUNT(*) FROM "{name}_03"').fetchone()[0]
    if count == 0:
        msg = f"mosaic: no child was assigned to any parent for {name}"
        raise RuntimeError(msg)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_03" AS
        SELECT * EXCLUDE (fid), ROW_NUMBER() OVER () AS fid FROM "{name}_03"
    """)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_full"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_parts"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_tiles"')

    stitch.main(conn, name, debug=debug)
    outputs.main(
        conn,
        name,
        output_path,
        issues_path,
        code_join=bool(parent_match_column and child_match_column),
        passthrough=passthrough,
        debug=debug,
    )
