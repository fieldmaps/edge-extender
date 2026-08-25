"""topo-tools CLI: click entry point."""

import glob
from logging import INFO, basicConfig, getLogger
from pathlib import Path

import click

from topo_tools.api import change as _change
from topo_tools.api import dissolve as _dissolve
from topo_tools.api import edge_clip as _edge_clip
from topo_tools.api import edge_extend as _edge_extend
from topo_tools.api import edge_match as _edge_match
from topo_tools.api import edge_mosaic as _edge_mosaic
from topo_tools.api import edge_stitch as _edge_stitch
from topo_tools.api import schema_crosswalk as _schema_crosswalk
from topo_tools.api import schema_fill as _schema_fill
from topo_tools.api import schema_map as _schema_map
from topo_tools.api import schema_refactor as _schema_refactor
from topo_tools.api import topo_clean as _topo_clean
from topo_tools.api import topo_detect as _topo_detect
from topo_tools.core.change._constants import TAU_MATCH_DEFAULT, TAU_SAME_DEFAULT

basicConfig(level=INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = getLogger(__name__)


def _split_commas(values: tuple[str, ...]) -> list[str]:
    """Flatten repeated --flag occurrences, each optionally comma-separated."""
    return [v for raw in values for v in raw.split(",")]


@click.group()
@click.version_option(package_name="topo-tools", prog_name="topo-tools")
def cli() -> None:
    """topo-tools: DuckDB-powered geospatial topology utilities."""


@cli.command(name="edge-extend")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
def edge_extend(  # noqa: PLR0913, PLR0917
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
      topo-tools edge-extend example.geojson

      \b
      # Explicit output
      topo-tools edge-extend example.gpkg example_extended.gpkg

      \b
      # Error instead of silently overwriting an existing output
      topo-tools edge-extend example.parquet example_extended.parquet --overwrite=false
    """
    logger.info("--debug=%s", debug)
    try:
        _edge_extend(
            input_file,
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="topo-detect")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "issues", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def topo_detect(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Scan a single polygon layer for gap/overlap coverage defects.

    OUTPUT_FILE defaults to INPUT_FILE with an "_issues" suffix if omitted.

    \b
    Examples:
      # Basic run, output name chosen automatically
      topo-tools topo-detect example.geojson

      \b
      # Explicit output
      topo-tools topo-detect example.gpkg example_issues.gpkg
    """
    logger.info("--debug=%s", debug)
    try:
        _topo_detect(
            input_file,
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
    "--group-by",
    "group_by",
    envvar="GROUP_BY",
    required=True,
    multiple=True,
    help="Column name(s) to group by [may be repeated, and each value MAY be "
    "comma-separated].",
)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "dissolve", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def dissolve(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    group_by: tuple[str, ...],
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Aggregate a polygon layer into a coarser one by grouping on attribute columns.

    OUTPUT_FILE defaults to INPUT_FILE with a "_dissolved" suffix if omitted.
    Every column not in --group-by is kept via any_value if it's actually
    constant within every group, dropped (with a warning) if not. A NULL
    value in a --group-by column forms its own group like any other value,
    matching GDAL's `combine --group-by`.

    \b
    Examples:
      # Dissolve admin3 into admin2; ancestor columns constant per group
      # (e.g. adm1_name) are kept automatically, adm3's own columns are
      # dropped automatically since they vary within each admin2 group
      topo-tools dissolve adm3.geojson --group-by adm2_pcode
    """
    logger.info("--debug=%s", debug)
    try:
        _dissolve(
            input_file,
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            group_by=_split_commas(group_by),
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="topo-clean")
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
    default=None,
    help="'thin' (fill thin/sliver-shaped gaps regardless of width), 'all' "
    "(fill every detected gap), or a number in decimal degrees (the layer's "
    "EPSG:4326 units, matches GDAL/OGR convention, not meters). Omit to fill "
    "only floating-point-noise-scale gaps (the default).",
)
@click.option(
    "--snapping-distance",
    envvar="SNAPPING_DISTANCE",
    type=str,
    default=None,
    help="A number in decimal degrees. Omit to snap at SNAP_TOLERANCE (the "
    "default). Noding robustness knob only.",
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
def topo_clean(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    issues_file: str | None,
    maximum_gap_width: str | None,
    snapping_distance: str | None,
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
      # Basic run: fills only floating-point-noise-scale gaps (the default)
      topo-tools topo-clean example.geojson

      \b
      # Fill thin/sliver-shaped gaps regardless of width
      topo-tools topo-clean example.gpkg --maximum-gap-width thin

      \b
      # Fill every detected gap, not just slivers
      topo-tools topo-clean example.gpkg --maximum-gap-width all

      \b
      # Cap gap-filling at ~0.0001 degrees (~11m at the equator)
      topo-tools topo-clean example.parquet --maximum-gap-width 0.0001
    """
    logger.info(
        "--maximum-gap-width=%s --snapping-distance=%s --debug=%s",
        maximum_gap_width,
        snapping_distance,
        debug,
    )
    try:
        _topo_clean(
            input_file,
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
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
            old_file,
            new_file,
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


@cli.command(name="edge-match")
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
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
@click.option(
    "--match-column",
    envvar="MATCH_COLUMN",
    default=None,
    help=(
        "Column name shared by both layers, used as an exact code join "
        "(e.g. a pcode) that wins over spatial overlap on disagreement. "
        "Mutually exclusive with --parent-match-column/--child-match-column."
    ),
)
@click.option(
    "--parent-match-column",
    envvar="PARENT_MATCH_COLUMN",
    default=None,
    help="Parent-side code column, when it's named differently than the child's.",
)
@click.option(
    "--child-match-column",
    envvar="CHILD_MATCH_COLUMN",
    default=None,
    help="Child-side code column, when it's named differently than the parent's.",
)
def edge_match(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
    match_column: str | None,
    parent_match_column: str | None,
    child_match_column: str | None,
) -> None:
    r"""Match children to parents by largest overlap, then extend to fill gaps.

    OUTPUT_FILE defaults to INPUT_FILE with a "_matched" suffix if omitted.

    \b
    Examples:
      # Fit an admin4 layer into a single country boundary
      topo-tools edge-match adm4.geojson adm0.geojson

      \b
      # Fit admin3 into admin2 groups, each cleaned against its own parent
      topo-tools edge-match adm3.gpkg adm2.gpkg adm3_matched.gpkg

      \b
      # Prefer an existing pcode join over spatial overlap where they disagree
      topo-tools edge-match adm3.gpkg adm2.gpkg --match-column pcode
    """
    logger.info("--debug=%s", debug)
    try:
        _edge_match(
            input_file,
            clip_file,
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
            match_column=match_column,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="edge-mosaic")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--input",
    "extra_inputs",
    envvar="EXTRA_INPUTS",
    multiple=True,
    help=(
        "Additional children file beyond INPUT_FILE, combined with it "
        "[may be repeated, and each value MAY be comma-separated]."
    ),
)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
@click.option(
    "--match-column",
    envvar="MATCH_COLUMN",
    default=None,
    help=(
        "Column name shared by both layers, used as an exact code join "
        "(e.g. a pcode) that wins over spatial overlap on disagreement. "
        "Mutually exclusive with --parent-match-column/--child-match-column."
    ),
)
@click.option(
    "--parent-match-column",
    envvar="PARENT_MATCH_COLUMN",
    default=None,
    help="Parent-side code column, when it's named differently than the child's.",
)
@click.option(
    "--child-match-column",
    envvar="CHILD_MATCH_COLUMN",
    default=None,
    help="Child-side code column, when it's named differently than the parent's.",
)
def edge_mosaic(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    extra_inputs: tuple[str, ...],
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
    match_column: str | None,
    parent_match_column: str | None,
    child_match_column: str | None,
) -> None:
    r"""Fit an already-extended children layer into a new parent/clip layer.

    OUTPUT_FILE defaults to INPUT_FILE with a "_mosaicked" suffix if omitted;
    it is required when INPUT_FILE is a glob matching more than one file, or
    when --input is given.

    \b
    Examples:
      # Re-clip a pre-extended admin3 layer against a new admin0 boundary
      topo-tools edge-mosaic adm3_extended.parquet adm0_new.geojson

      \b
      # Combine every country's pre-extended layer, re-clip against a world admin0
      topo-tools edge-mosaic "*/latest/adm2/extended.parquet" world_adm0.geojson \
        out.parquet

      \b
      # Combine explicit files instead of a glob (--input MAY be repeated
      # and/or comma-separated)
      topo-tools edge-mosaic afg.parquet world_adm0.geojson out.parquet \
        --input ago.parquet,are.parquet

      \b
      # Prefer an existing pcode join over spatial overlap where they disagree
      topo-tools edge-mosaic adm3_extended.parquet adm0_new.geojson --match-column pcode
    """
    logger.info("--debug=%s", debug)
    if any(ch in input_file for ch in "*?["):
        matches = sorted(glob.glob(input_file, recursive=True))  # noqa: PTH207 (arbitrary pattern, not anchored to one Path)
        if not matches:
            msg = f"no files matched: {input_file}"
            raise click.ClickException(msg)
        base_inputs = [Path(p) for p in matches]
    else:
        base_inputs = [input_file]
    all_inputs = base_inputs + list(_split_commas(extra_inputs))
    resolved_input: str | Path | list[str | Path] = (
        all_inputs[0] if len(all_inputs) == 1 else all_inputs
    )
    try:
        _edge_mosaic(
            resolved_input,
            clip_file,
            Path(output_file) if output_file is not None else None,
            Path(issues_file) if issues_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
            match_column=match_column,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="edge-stitch")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--input",
    "extra_inputs",
    envvar="EXTRA_INPUTS",
    multiple=True,
    help=(
        "Additional already-tiled file beyond INPUT_FILE, combined with it "
        "[may be repeated, and each value MAY be comma-separated]."
    ),
)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help='Issues report path. Defaults to OUTPUT_FILE with an "_issues" suffix.',
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
def edge_stitch(  # noqa: PLR0913, PLR0917
    input_file: str,
    output_file: str | None,
    extra_inputs: tuple[str, ...],
    issues_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Close seams in an already-tiled polygon layer via coverage-clean.

    OUTPUT_FILE defaults to INPUT_FILE with a "_stitched" suffix if omitted;
    it is required when INPUT_FILE is a glob matching more than one file, or
    when --input is given.

    \b
    Examples:
      # Basic run, output name chosen automatically
      topo-tools edge-stitch tiled.geojson

      \b
      # Explicit output
      topo-tools edge-stitch tiled.gpkg stitched.gpkg

      \b
      # Combine every already-clipped file into one global stitched output
      topo-tools edge-stitch "tmp/clipped/*.parquet" stitched.parquet

      \b
      # Combine explicit files instead of a glob (--input MAY be repeated
      # and/or comma-separated)
      topo-tools edge-stitch afg.parquet stitched.parquet \
        --input ago.parquet,are.parquet

      \b
      # Error instead of silently overwriting an existing output
      topo-tools edge-stitch tiled.parquet stitched.parquet --overwrite=false
    """
    logger.info("--debug=%s", debug)
    if any(ch in input_file for ch in "*?["):
        matches = sorted(glob.glob(input_file, recursive=True))  # noqa: PTH207 (arbitrary pattern, not anchored to one Path)
        if not matches:
            msg = f"no files matched: {input_file}"
            raise click.ClickException(msg)
        base_inputs = [Path(p) for p in matches]
    else:
        base_inputs = [input_file]
    all_inputs = base_inputs + list(_split_commas(extra_inputs))
    resolved_input: str | Path | list[str | Path] = (
        all_inputs[0] if len(all_inputs) == 1 else all_inputs
    )
    try:
        _edge_stitch(
            resolved_input,
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


@cli.command(name="schema-fill")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument(
    "target_schema_file", envvar="TARGET_SCHEMA_FILE", required=False, default=None
)
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "fill", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
@click.option(
    "--depth-column",
    envvar="DEPTH_COLUMN",
    default="adm_lvl",
    show_default=True,
    help="Name of the new column stamping each row's real, pre-fill depth.",
)
def schema_fill(  # noqa: PLR0913, PLR0917
    input_file: str,
    target_schema_file: str | None,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
    depth_column: str,
) -> None:
    r"""Cascade each admin-hierarchy column down from its nearest shallower level.

    Stamps a new depth column (default "adm_lvl") with each row's real depth.
    """
    logger.info("--debug=%s", debug)
    try:
        _schema_fill(
            input_file,
            target_schema_file,
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
            depth_column=depth_column,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="schema-map")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument(
    "target_schema_file", envvar="TARGET_SCHEMA_FILE", required=False, default=None
)
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--layer",
    envvar="LAYER",
    default=None,
    help="Layer name, for a multi-layer source (e.g. FileGDB). Auto-detected "
    "when possible; required if auto-detection can't resolve it to exactly "
    "one geometry-bearing layer.",
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "map", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def schema_map(  # noqa: PLR0913, PLR0917
    input_file: str,
    target_schema_file: str | None,
    output_file: str | None,
    layer: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Map a source-column -> target-schema crosswalk for one input file.

    TARGET_SCHEMA_FILE is a YAML config of canonical target fields; if
    omitted, defaults to the bundled COD-AB schema
    (topo_tools/core/schema_map/data/cod-ab.yaml). OUTPUT_FILE defaults to
    INPUT_FILE with a "_crosswalk.csv" name if omitted. Never renames
    anything itself; review/edit the crosswalk, then run schema-refactor.

    \b
    Examples:
      # Basic run: default (COD-AB) schema, output name chosen automatically
      topo-tools schema-map example.geojson

      \b
      # Custom target schema
      topo-tools schema-map example.geojson target-schema.yaml
    """
    logger.info("--debug=%s", debug)
    try:
        _schema_map(
            input_file,
            target_schema_file,
            Path(output_file) if output_file is not None else None,
            layer=layer,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="schema-refactor")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("crosswalk_file", envvar="CROSSWALK_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "rename", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def schema_refactor(  # noqa: PLR0913, PLR0917
    input_file: str,
    crosswalk_file: str,
    output_file: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Rename/drop columns per a crosswalk from schema-map (possibly edited).

    CROSSWALK_FILE is the CSV crosswalk schema-map wrote (or a hand-edited copy
    of it). Raises if the crosswalk's columns don't exactly match
    INPUT_FILE's, catching a stale crosswalk or wrong input file.
    OUTPUT_FILE defaults to INPUT_FILE with a "_mapped" suffix if omitted.

    \b
    Examples:
      # Basic run, output name chosen automatically
      topo-tools schema-refactor example.geojson crosswalk.csv

      \b
      # Explicit output
      topo-tools schema-refactor example.gpkg crosswalk.csv example_mapped.gpkg
    """
    logger.info("--debug=%s", debug)
    try:
        _schema_refactor(
            input_file,
            crosswalk_file,
            Path(output_file) if output_file is not None else None,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="schema-crosswalk")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument(
    "target_schema_file", envvar="TARGET_SCHEMA_FILE", required=False, default=None
)
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.argument("crosswalk_file", envvar="CROSSWALK_FILE", required=False, default=None)
@click.option(
    "--layer",
    envvar="LAYER",
    default=None,
    help="Layer name, for a multi-layer source (e.g. FileGDB). Auto-detected "
    "when possible; required if auto-detection can't resolve it to exactly "
    "one geometry-bearing layer.",
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "map", "apply", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
def schema_crosswalk(  # noqa: PLR0913, PLR0917
    input_file: str,
    target_schema_file: str | None,
    output_file: str | None,
    crosswalk_file: str | None,
    layer: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
) -> None:
    r"""Map a crosswalk, then apply it (schema-map + schema-refactor, combined).

    TARGET_SCHEMA_FILE defaults to the bundled COD-AB schema. OUTPUT_FILE
    defaults to INPUT_FILE with a "_mapped" suffix; CROSSWALK_FILE defaults
    to INPUT_FILE with a "_crosswalk.csv" name. To iterate, hand-edit the
    written crosswalk CSV and re-run schema-refactor on it, not schema-crosswalk
    again (which always maps fresh).

    \b
    Examples:
      # Basic run: default (COD-AB) schema, output names chosen automatically
      topo-tools schema-crosswalk example.geojson

      \b
      # Custom target schema, explicit outputs
      topo-tools schema-crosswalk example.geojson target-schema.yaml \
          example_mapped.geojson example_crosswalk.csv
    """
    logger.info("--debug=%s", debug)
    try:
        _schema_crosswalk(
            input_file,
            target_schema_file,
            Path(output_file) if output_file is not None else None,
            Path(crosswalk_file) if crosswalk_file is not None else None,
            layer=layer,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e


@cli.command(name="edge-clip")
@click.argument("input_file", envvar="INPUT_FILE")
@click.argument("clip_file", envvar="CLIP_FILE")
@click.argument("output_file", envvar="OUTPUT_FILE", required=False, default=None)
@click.option(
    "--input",
    "extra_inputs",
    envvar="EXTRA_INPUTS",
    multiple=True,
    help=(
        "Additional children file beyond INPUT_FILE, paired by order with "
        "--output [may be repeated, and each value MAY be comma-separated]."
    ),
)
@click.option(
    "--output",
    "extra_outputs",
    envvar="EXTRA_OUTPUTS",
    multiple=True,
    help=(
        "Additional output file beyond OUTPUT_FILE, paired by order with "
        "--input [may be repeated, and each value MAY be comma-separated]."
    ),
)
@click.option(
    "--issues-file",
    envvar="ISSUES_FILE",
    default=None,
    help=(
        "Issues report path, only used with --match-column/--parent-match-column. "
        'Defaults to OUTPUT_FILE with an "_issues" suffix.'
    ),
)
@click.option(
    "--issues",
    "extra_issues",
    envvar="EXTRA_ISSUES",
    multiple=True,
    help=(
        "Additional issues report beyond --issues-file, paired by order with "
        "--input/--output [may be repeated, and each value MAY be comma-separated]."
    ),
)
@click.option(
    "--name",
    envvar="NAME",
    default=None,
    help="Run name for internal tables/tmp files. Required when --input is given.",
)
@click.option(
    "--overwrite",
    envvar="OVERWRITE",
    type=bool,
    default=True,
    show_default=True,
    help="Overwrite an existing output; pass --overwrite=false to error instead.",
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
    type=click.Choice(["inputs", "assign", "clip", "outputs"]),
    default=None,
    help="Run only one named stage.",
)
@click.option(
    "--match-column",
    envvar="MATCH_COLUMN",
    default=None,
    help=(
        "Column name shared by both layers, used as an exact code join "
        "(e.g. a pcode) that wins over spatial overlap on disagreement. "
        "Mutually exclusive with --parent-match-column/--child-match-column."
    ),
)
@click.option(
    "--parent-match-column",
    envvar="PARENT_MATCH_COLUMN",
    default=None,
    help="Parent-side code column, when it's named differently than the child's.",
)
@click.option(
    "--child-match-column",
    envvar="CHILD_MATCH_COLUMN",
    default=None,
    help="Child-side code column, when it's named differently than the parent's.",
)
def edge_clip(  # noqa: PLR0913, PLR0917
    input_file: str,
    clip_file: str,
    output_file: str | None,
    extra_inputs: tuple[str, ...],
    extra_outputs: tuple[str, ...],
    issues_file: str | None,
    extra_issues: tuple[str, ...],
    name: str | None,
    overwrite: bool,  # noqa: FBT001
    threads: int | None,
    debug: bool,  # noqa: FBT001
    tmp_dir: str | None,
    step: str | None,
    match_column: str | None,
    parent_match_column: str | None,
    child_match_column: str | None,
) -> None:
    r"""Assign each child to its parent, then clip it to that parent's geometry.

    INPUT_FILE and CLIP_FILE are both raw polygon layers; INPUT_FILE's
    children are assigned to CLIP_FILE's parents internally (assign-one)
    before clipping. OUTPUT_FILE defaults to INPUT_FILE with a "_clipped"
    suffix if omitted.

    \b
    Examples:
      # Clip a children layer against a parent/clip layer
      topo-tools edge-clip children.parquet adm1.geojson

      \b
      # Explicit output
      topo-tools edge-clip children.parquet adm1.geojson clipped.parquet

      \b
      # Multiple children files sharing one CLIP_FILE load (--input/--output
      # MAY each be repeated and/or comma-separated; --name is required)
      topo-tools edge-clip afg.parquet world_adm0.geojson afg_out.parquet \
        --input ago.parquet,are.parquet --output ago_out.parquet,are_out.parquet \
        --name portolan_batch

      \b
      # Prefer an existing pcode join over spatial overlap where they disagree
      topo-tools edge-clip children.parquet adm1.geojson --match-column pcode
    """
    logger.info("--debug=%s", debug)
    if extra_inputs and output_file is None:
        msg = "OUTPUT_FILE is required when --input is given"
        raise click.ClickException(msg)

    extra_inputs_split = _split_commas(extra_inputs)
    extra_outputs_split = _split_commas(extra_outputs)
    extra_issues_split = _split_commas(extra_issues)
    if extra_inputs_split:
        children: str | Path | list[str | Path] = [
            input_file,
            *extra_inputs_split,
        ]
        outputs: str | Path | list[str | Path] | None = [
            output_file,
            *extra_outputs_split,
        ]
        issues: str | Path | list[str | Path] | None = (
            [issues_file, *extra_issues_split] if issues_file is not None else None
        )
    else:
        children = input_file
        outputs = Path(output_file) if output_file is not None else None
        issues = Path(issues_file) if issues_file is not None else None

    try:
        _edge_clip(
            children,
            clip_file,
            outputs,
            issues,
            name=name,
            threads=threads,
            tmp_dir=tmp_dir,
            overwrite=overwrite,
            debug=debug,
            step=step,
            match_column=match_column,
            parent_match_column=parent_match_column,
            child_match_column=child_match_column,
        )
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e
