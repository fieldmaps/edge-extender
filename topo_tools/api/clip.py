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
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import export_geometry_table

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "assign", "clip", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_child_01", "{n}_parent_01"],
    "assign": ["{n}_02_pairs", "{n}_02_assign", "{n}_02_unassigned"],
    "clip": ["{n}_03"],
    "outputs": [],
}

_PER_FILE_TABLES = ("_child_01", "_02_pairs", "_02_assign", "_02_unassigned", "_03")


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
    majority-vote parent), processed one file at a time so only one file's
    geometry is ever resident alongside the shared parent. output_paths MUST
    then be an equal-length list, one destination per children file, and
    name MUST be given explicitly (there's no single path to derive one
    from); step MUST be None in this case (no per-step resumability for the
    multi-file loop). With a single scalar children_paths, output_paths
    defaults to children_paths with a "_clipped" suffix, name defaults
    similarly, and step works as usual.
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

    if single_path is None and step is not None:
        msg = "step is not supported when multiple children_paths are given"
        raise ValueError(msg)

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
                tmp_dir_path,
                threads=threads,
                debug=debug,
            )
        else:
            _clip_single_file(
                conn,
                name,
                children,
                parent_path,
                outputs_list[0],
                tmp_dir_path,
                threads=threads,
                debug=debug,
                step=step,
            )
        logger.info("done: %s", name)


def _clip_single_file(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    children: list[Path],
    parent_path: Path,
    output_path: Path,
    tmp_dir_path: Path,
    *,
    threads: int | None,
    debug: bool,
    step: str | None,
) -> None:
    """Run clip's four named stages once, in order, over one children file."""
    dest_by_source = {str(children[0]): output_path}
    for s in _STEP_ORDER:
        if step and step != s:
            continue
        if debug:
            logger.info("=== %s ===", s)
        if s == "inputs":
            load_children(conn, name, children)
            load_parent(conn, name, parent_path)
        elif s == "assign":
            assign_one(conn, name)
        elif s == "clip":
            clip_stage.main(conn, name, tmp_dir_path, threads=threads, debug=debug)
        elif s == "outputs":
            outputs.main(conn, name, dest_by_source, debug=debug)
    maybe_export_debug_tables(conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug)


def _clip_each_file(  # noqa: PLR0913, PLR0917
    conn: DuckDBPyConnection,
    name: str,
    children: list[Path],
    parent_path: Path,
    outputs_list: list[Path],
    tmp_dir_path: Path,
    *,
    threads: int | None,
    debug: bool,
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

    staged: list[tuple[Path, Path]] = []
    failed: list[str] = []
    for child_path, dest in zip(children, outputs_list, strict=True):
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_parent_01" AS
            SELECT * FROM "{name}_parent_full"
        """)
        load_children(conn, name, [child_path])
        assign_one(conn, name, use_cached_tiles=True)
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

        if not debug:
            conn.execute(f'DROP VIEW IF EXISTS "{name}_03_one"')
            for tbl in _PER_FILE_TABLES:
                conn.execute(f'DROP TABLE IF EXISTS "{name}{tbl}"')

    if failed:
        for tmp_path, _ in staged:
            tmp_path.unlink(missing_ok=True)
        msg = f"clip: no child survived clipping for: {failed}"
        raise RuntimeError(msg)

    for tmp_path, dest in staged:
        tmp_path.replace(dest)
    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_parent_full"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_parts"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02_parent_tiles"')
