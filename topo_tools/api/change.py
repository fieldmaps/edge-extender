"""Public API: compare two polygon layer versions and classify what changed."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.change import _01_inputs as inputs
from topo_tools.core.change import _02_overlap as overlap
from topo_tools.core.change import _03_classify as classify
from topo_tools.core.change import _04_outputs as outputs
from topo_tools.core.change._columns import detect_code_column, detect_name_column
from topo_tools.core.change._constants import (
    TABLE_COPY_OPTS,
    TAU_MATCH_DEFAULT,
    TAU_SAME_DEFAULT,
)
from topo_tools.core.constants import COPY_OPTS
from topo_tools.core.duckdb_utils import (
    maybe_export_debug_tables,
    pipeline_connection,
    resolve_tmp_dir,
)
from topo_tools.core.io import (
    check_overwrite,
    input_basename,
    resolve_input_path,
)

logger = getLogger(__name__)

_STEP_ORDER = ["inputs", "overlap", "classify", "outputs"]

_STEP_TABLES = {
    "inputs": ["{n}_a_01", "{n}_b_01"],
    "overlap": ["{n}_02"],
    "classify": ["{n}_03a", "{n}_03b", "{n}_03c"],
    "outputs": [],
}


def _resolve_column(
    conn: DuckDBPyConnection, table: str, explicit: str | None, *, kind: str, side: str
) -> str | None:
    if explicit is not None:
        return explicit
    detector = detect_code_column if kind == "code" else detect_name_column
    column = detector(conn, table)
    if column is None:
        msg = (
            f"--link-by-{kind} was requested but no {kind} column could be "
            f"auto-detected on the {side} side; pass --{kind}-column-{side} explicitly"
        )
        raise ValueError(msg)
    return column


def change(  # noqa: C901, PLR0912, PLR0913
    old_path: str | Path,
    new_path: str | Path,
    output_path: str | Path | None = None,
    overlay_path: str | Path | None = None,
    *,
    tau_match: float = TAU_MATCH_DEFAULT,
    tau_same: float = TAU_SAME_DEFAULT,
    link_by_code: bool = False,
    link_by_name: bool = False,
    link_mode: str = "either",
    code_column_a: str | None = None,
    code_column_b: str | None = None,
    name_column_a: str | None = None,
    name_column_b: str | None = None,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = True,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Compare two polygon layer versions and classify every unit's relationship.

    Processes exactly one old file + one new file per call.
    """
    if step is not None and step not in _STEP_ORDER:
        msg = f"step must be one of {_STEP_ORDER}, got {step!r}"
        raise ValueError(msg)
    if link_mode not in ("either", "both"):
        msg = f"link_mode must be 'either' or 'both', got {link_mode!r}"
        raise ValueError(msg)

    old_path = resolve_input_path(old_path)
    new_path = resolve_input_path(new_path)
    if output_path is not None:
        output_path = Path(output_path)
    else:
        old_stem = Path(input_basename(old_path)).stem
        new_stem = Path(input_basename(new_path)).stem
        directory = old_path.parent if isinstance(old_path, Path) else Path()
        output_path = directory / f"{old_stem}_{new_stem}_changelog.csv"
    if output_path.suffix not in TABLE_COPY_OPTS:
        msg = (
            f"output file must be one of {sorted(TABLE_COPY_OPTS)} (a tabular "
            "format, the changelog has no geometry column), got "
            f"{output_path.suffix!r}"
        )
        raise ValueError(msg)
    overlay_path = (
        Path(overlay_path)
        if overlay_path is not None
        else output_path.with_stem(output_path.stem + "_overlay").with_suffix(
            Path(input_basename(old_path)).suffix
        )
    )
    if overlay_path.suffix not in COPY_OPTS:
        msg = (
            f"overlay file must be one of {sorted(COPY_OPTS)}, "
            f"got {overlay_path.suffix!r}"
        )
        raise ValueError(msg)
    check_overwrite(output_path, overwrite=overwrite)
    check_overwrite(overlay_path, overwrite=overwrite)

    # "_changelog" keeps every table/file this call creates distinct from an
    # extend()/match()/clean() run against the same old_path/tmp_dir, same
    # collision-avoidance reasoning as match's "_match" and clean's "_clean".
    name = input_basename(old_path).replace(".", "_") + "_changelog"

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
                inputs.main(conn, name, old_path, new_path)
            elif s == "overlap":
                overlap.main(conn, name)
            elif s == "classify":
                resolved_code_a = (
                    _resolve_column(
                        conn, f"{name}_a_01", code_column_a, kind="code", side="a"
                    )
                    if link_by_code
                    else code_column_a
                )
                resolved_code_b = (
                    _resolve_column(
                        conn, f"{name}_b_01", code_column_b, kind="code", side="b"
                    )
                    if link_by_code
                    else code_column_b
                )
                resolved_name_a = (
                    _resolve_column(
                        conn, f"{name}_a_01", name_column_a, kind="name", side="a"
                    )
                    if link_by_name
                    else name_column_a
                )
                resolved_name_b = (
                    _resolve_column(
                        conn, f"{name}_b_01", name_column_b, kind="name", side="b"
                    )
                    if link_by_name
                    else name_column_b
                )
                classify.main(
                    conn,
                    name,
                    tau_match=tau_match,
                    tau_same=tau_same,
                    link_by_code=link_by_code,
                    link_by_name=link_by_name,
                    link_mode=link_mode,
                    code_col_a=resolved_code_a,
                    code_col_b=resolved_code_b,
                    name_col_a=resolved_name_a,
                    name_col_b=resolved_name_b,
                )
            elif s == "outputs":
                outputs.main(conn, name, output_path, overlay_path, debug=debug)
        maybe_export_debug_tables(
            conn, tmp_dir_path, name, step, _STEP_TABLES, debug=debug
        )
        logger.info("done: %s", name)
