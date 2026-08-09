"""Public API: crosswalk each child to the parent it shares the largest area with."""

from pathlib import Path

from topo_tools.core.assign import _02_many as _strategy

from ._assign import run


def assign_many(  # noqa: PLR0913
    children_paths: str | Path | list[str | Path],
    parent_path: str | Path,
    output_path: str | Path | None = None,
    issues_path: str | Path | None = None,
    *,
    threads: int | None = None,
    tmp_dir: str | Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
    step: str | None = None,
) -> None:
    """Crosswalk each child to its own plurality-overlap parent.

    Each child decides independently, so one file's children MAY scatter
    across many different parents. children_paths MAY be a list; output_path
    is then required, since there's no single filename to default from.
    """
    run(
        children_paths,
        parent_path,
        output_path,
        issues_path,
        assign_module=_strategy,
        name_suffix="_assign_many",
        threads=threads,
        tmp_dir=tmp_dir,
        overwrite=overwrite,
        debug=debug,
        step=step,
    )
