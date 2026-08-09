"""topo-tools CLI: click entry point."""

import glob
from logging import INFO, basicConfig, getLogger
from pathlib import Path

import click

from topo_tools.api import assign_many as _assign_many
from topo_tools.api import assign_one as _assign_one
from topo_tools.api import change as _change
from topo_tools.api import clean as _clean
from topo_tools.api import clip as _clip
from topo_tools.api import extend as _extend
from topo_tools.api import match as _match
from topo_tools.api import mosaic as _mosaic
from topo_tools.api import stitch as _stitch
from topo_tools.core.change._constants import TAU_MATCH_DEFAULT, TAU_SAME_DEFAULT

basicConfig(level=INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = getLogger(__name__)


@click.group()
@click.version_option(package_name="topo-tools", prog_name="topo-tools")
def cli() -> None:
    """topo-tools: DuckDB-powered geospatial topology utilities."""


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "lines", "attempt", "merge", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def extend(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Extend polygon boundaries outward with Voronoi diagrams to fill coverage gaps.

    OUTPUT_FILE defaults to INPUT_FILE with an "_extended" suffix if omitted.

    \b
    Examples:
      # Basic run, output name chosen automatically
      topo-tools extend example.geojson

      \b
      # Explicit output
      topo-tools extend example.gpkg example_extended.gpkg

      \b
      # Rerun and overwrite a previous output
      topo-tools extend example.parquet example_extended.parquet --overwrite
    """
    logger.info("--debug=%s", debug)
    try:
        _extend(
            Path(input_file),
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--maximum-gap-width",
    envvar="MAXIMUM_GAP_WIDTH",
    type=str,
    default="auto",
    show_default=True,
    help="'auto' (fill only thin/sliver-shaped gaps), 'all' (fill every detected "
    "gap), or a number in decimal degrees (the layer's EPSG:4326 units -- "
    "matches GDAL/OGR convention, not meters).",
)
@click.option(
    "--snapping-distance",
    envvar="SNAPPING_DISTANCE",
    type=str,
    default="auto",
    show_default=True,
    help="'auto' (GEOS's computed default) or a number in decimal degrees. Noding "
    "robustness knob only.",
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "issues", "clean", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def clean(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    issues_file: str | None,
    maximum_gap_width: str,
    snapping_distance: str,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Detect and fix gap/overlap defects in a single polygon layer.

    OUTPUT_FILE defaults to INPUT_FILE with a "_cleaned" suffix if omitted.

    \b
    Examples:
      # Basic run: auto-fill only thin/sliver-shaped gaps, leave the rest for review
      topo-tools clean example.geojson

      \b
      # Fill every detected gap, not just slivers
      topo-tools clean example.gpkg --maximum-gap-width all

      \b
      # Cap gap-filling at ~0.0001 degrees (~11m at the equator)
      topo-tools clean example.parquet --maximum-gap-width 0.0001
    """
    logger.info(
        "--maximum-gap-width=%s --snapping-distance=%s --debug=%s",
        maximum_gap_width,
        snapping_distance,
        debug,
    )
    try:
        _clean(
            Path(input_file),
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            maximum_gap_width=maximum_gap_width,
            snapping_distance=snapping_distance,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, ValueError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("old_file", envvar="OLD_FILE")
@click.argument("new_file", envvar="NEW_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overlay-file",
    envvar="OVERLAY_FILE",
    default=None,
    help='Spatial overlay layer path. Defaults to OUTPUT_FILE with an "_overlay" '
    "suffix.",
)
@click.option(
    "--tau-match",
    envvar="TAU_MATCH",
    type=float,
    default=TAU_MATCH_DEFAULT,
    show_default=True,
    help="Minimum overlap coverage for two units to be spatially linked.",
)
@click.option(
    "--tau-same",
    envvar="TAU_SAME",
    type=float,
    default=TAU_SAME_DEFAULT,
    show_default=True,
    help="Minimum IoU for a 1:1 linked pair to be unchanged/renamed rather than "
    "modified.",
)
@click.option(
    "--link-by-code",
    envvar="LINK_BY_CODE",
    is_flag=True,
    help="Also link units sharing a unique code value across versions.",
)
@click.option(
    "--link-by-name",
    envvar="LINK_BY_NAME",
    is_flag=True,
    help="Also link units sharing a unique name value across versions.",
)
@click.option(
    "--link-mode",
    envvar="LINK_MODE",
    type=click.Choice(["either", "both"]),
    default="either",
    show_default=True,
    help="How code/name identity matches combine (only matters if both flags are set).",
)
@click.option(
    "--code-column-a",
    envvar="CODE_COLUMN_A",
    default=None,
    help="Old-side code column; auto-detected if omitted.",
)
@click.option(
    "--code-column-b",
    envvar="CODE_COLUMN_B",
    default=None,
    help="New-side code column; auto-detected if omitted.",
)
@click.option(
    "--name-column-a",
    envvar="NAME_COLUMN_A",
    default=None,
    help="Old-side name column; auto-detected if omitted.",
)
@click.option(
    "--name-column-b",
    envvar="NAME_COLUMN_B",
    default=None,
    help="New-side name column; auto-detected if omitted.",
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "overlap", "classify", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def change(  # noqa: PLR0913, PLR0917
    old_file: str,
    new_file: str,
    output_file: str | None,
    overlay_file: str | None,
    tau_match: float,
    tau_same: float,
    link_by_code: bool,  # noqa: FBT001
    link_by_name: bool,  # noqa: FBT001
    link_mode: str,
    code_column_a: str | None,
    code_column_b: str | None,
    name_column_a: str | None,
    name_column_b: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Compare two polygon layer versions and classify what changed.

    OLD_FILE is the previous version, NEW_FILE is the new version. OUTPUT_FILE
    (the tabular changelog, CSV or Parquet) defaults to a name combining both
    stems with a "_changelog" suffix if omitted. A spatial overlay layer
    colored by relationship_class is always written alongside it.

    \b
    Examples:
      # Basic run, pure spatial matching
      topo-tools change admin2_2020.geojson admin2_2024.geojson

      \b
      # Also link units sharing a unique pcode across versions
      topo-tools change old.gpkg new.gpkg --link-by-code

      \b
      # Loosen the "related" threshold for heavily redrawn boundaries
      topo-tools change old.parquet new.parquet --tau-match 0.6
    """
    logger.info("--tau-match=%s --tau-same=%s --debug=%s", tau_match, tau_same, debug)
    try:
        _change(
            Path(old_file),
            Path(new_file),
            Path(output_file) if output_file is not None else None,
            Path(overlay_file) if overlay_file is not None else None,
            tau_match=tau_match,
            tau_same=tau_same,
            link_by_code=link_by_code,
            link_by_name=link_by_name,
            link_mode=link_mode,
            code_column_a=code_column_a,
            code_column_b=code_column_b,
            name_column_a=name_column_a,
            name_column_b=name_column_b,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, ValueError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "assign", "groups", "clip", "stitch", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def match(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Match children to parents by largest overlap, then extend to fill gaps.

    OUTPUT_FILE defaults to INPUT_FILE with a "_matched" suffix if omitted.

    \b
    Examples:
      # Fit an admin4 layer into a single country boundary
      topo-tools match adm4.geojson adm0.geojson

      \b
      # Fit admin3 into admin2 groups, each cleaned against its own parent
      topo-tools match adm3.gpkg adm2.gpkg adm3_matched.gpkg
    """
    logger.info("--debug=%s", debug)
    try:
        _match(
            Path(input_file),
            Path(clip_file),
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "assign", "clip", "stitch", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def mosaic(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Fit an already-extended children layer into a new parent/clip layer.

    OUTPUT_FILE defaults to INPUT_FILE with a "_mosaicked" suffix if omitted;
    it is required when INPUT_FILE is a glob matching more than one file.

    \b
    Examples:
      # Re-clip a pre-extended admin3 layer against a new admin0 boundary
      topo-tools mosaic adm3_extended.parquet adm0_new.geojson

      \b
      # Combine every country's pre-extended layer, re-clip against a world admin0
      topo-tools mosaic "*/latest/adm2/extended.parquet" world_adm0.geojson out.parquet
    """
    logger.info("--debug=%s", debug)
    if any(ch in input_file for ch in "*?["):
        matches = sorted(glob.glob(input_file, recursive=True))  # noqa: PTH207 -- arbitrary pattern, not anchored to one Path
        if not matches:
            msg = f"no files matched: {input_file}"
            raise click.ClickException(msg)
        resolved_input: Path | list[Path] = [Path(p) for p in matches]
    else:
        resolved_input = Path(input_file)
    try:
        _mosaic(
            resolved_input,
            Path(clip_file),
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "clean", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def stitch(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Close seams in an already-tiled polygon layer via coverage-clean.

    OUTPUT_FILE defaults to INPUT_FILE with a "_stitched" suffix if omitted.

    \b
    Examples:
      # Basic run, output name chosen automatically
      topo-tools stitch tiled.geojson

      \b
      # Explicit output
      topo-tools stitch tiled.gpkg stitched.gpkg

      \b
      # Rerun and overwrite a previous output
      topo-tools stitch tiled.parquet stitched.parquet --overwrite
    """
    logger.info("--debug=%s", debug)
    try:
        _stitch(
            Path(input_file),
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="assign-many")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "assign", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def assign_many(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Crosswalk each child to the parent it shares the largest area with.

    Each child decides independently, so one file's children MAY scatter
    across many different parents. Correct for raw/unextended geometry.
    OUTPUT_FILE defaults to INPUT_FILE with an "_assigned" suffix if
    omitted; it is required when INPUT_FILE is a glob matching more than
    one file.

    \b
    Examples:
      # Crosswalk one country's raw admin2 units to admin1 parents
      topo-tools assign-many adm2.geojson adm1.geojson

      \b
      # Crosswalk every country's raw admin2 units to a world admin0 layer
      topo-tools assign-many "*/latest/adm2.parquet" world_adm0.geojson out.parquet
    """
    logger.info("--debug=%s", debug)
    if any(ch in input_file for ch in "*?["):
        matches = sorted(glob.glob(input_file, recursive=True))  # noqa: PTH207 -- arbitrary pattern, not anchored to one Path
        if not matches:
            msg = f"no files matched: {input_file}"
            raise click.ClickException(msg)
        resolved_input: Path | list[Path] = [Path(p) for p in matches]
    else:
        resolved_input = Path(input_file)
    try:
        _assign_many(
            resolved_input,
            Path(clip_file),
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="assign-one")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "assign", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def assign_one(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Crosswalk a multi-file child set onto one shared majority-vote parent.

    Every child in one source file lands on one shared parent -- guards
    against already-extended/overshoot geometry crossing borders.
    OUTPUT_FILE defaults to INPUT_FILE with an "_assigned" suffix if
    omitted; it is required when INPUT_FILE is a glob matching more than
    one file.

    \b
    Examples:
      # Crosswalk one country's already-extended admin2 layer to admin1 parents
      topo-tools assign-one adm2_extended.geojson adm1.geojson

      \b
      # Crosswalk every country's pre-extended layer onto a world admin0
      topo-tools assign-one "*/latest/adm2/extended.parquet" world.geojson out.parquet
    """
    logger.info("--debug=%s", debug)
    if any(ch in input_file for ch in "*?["):
        matches = sorted(glob.glob(input_file, recursive=True))  # noqa: PTH207 -- arbitrary pattern, not anchored to one Path
        if not matches:
            msg = f"no files matched: {input_file}"
            raise click.ClickException(msg)
        resolved_input: Path | list[Path] = [Path(p) for p in matches]
    else:
        resolved_input = Path(input_file)
    try:
        _assign_one(
            resolved_input,
            Path(clip_file),
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite", envvar="OVERWRITE", is_flag=True, help="Overwrite existing output."
)
@click.option(
    "--threads", envvar="THREADS", type=int, default=None, help="DuckDB thread count."
)
@click.option(
    "--debug",
    envvar="DEBUG",
    is_flag=True,
    help="Keep intermediate tables, export to Parquet, log timing/memory per query.",
)
@click.option(
    "--tmp-dir",
    envvar="TMP_DIR",
    default=None,
    help="Intermediate DuckDB + Parquet location.",
)
@click.option(
    "--step",
    envvar="STEP",
    type=click.Choice(["inputs", "clip", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def clip(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Clip each child to its own already-assigned parent's geometry.

    INPUT_FILE MUST already carry a parent_fid column (e.g. assign-many's or
    assign-one's own output). OUTPUT_FILE defaults to INPUT_FILE with a
    "_clipped" suffix if omitted.

    \b
    Examples:
      # Clip an assign-many crosswalk down to its parents
      topo-tools clip children_assigned.parquet adm1.geojson

      \b
      # Explicit output
      topo-tools clip children_assigned.parquet adm1.geojson clipped.parquet
    """
    logger.info("--debug=%s", debug)
    try:
        _clip(
            Path(input_file),
            Path(clip_file),
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e
