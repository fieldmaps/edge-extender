"""Shared geodata read/write helpers."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from .constants import COPY_OPTS, RESERVED_COLUMN_NAMES
from .coverage import coverage_clean, has_valid_topology

logger = getLogger(__name__)


def read_and_reproject(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Read geodata, reproject to EPSG:4326, store as canonical table `{name}_01`."""
    read_expr = (
        f"SELECT * FROM '{path}'"
        if path.suffix == ".parquet"
        else f"SELECT * FROM ST_Read('{path}')"
    )

    schema = conn.execute(f"DESCRIBE {read_expr}").fetchall()
    geom_col, geom_type = next(
        (col[0], col[1]) for col in schema if col[1].startswith("GEOMETRY")
    )
    # A source column already named "fid"/"OGC_FID" would otherwise collide
    # with our own row_number() AS fid below (duplicate column) or with
    # GDAL's reserved FID handling on export (see RESERVED_COLUMN_NAMES);
    # rename it once here so nothing downstream has to guard against it.
    colliding_cols = [col[0] for col in schema if col[0] in RESERVED_COLUMN_NAMES]
    if colliding_cols:
        logger.warning(
            "renaming source column(s) %s to %s to avoid colliding with "
            "topo-tools' internal fid / GDAL's reserved OGC_FID field",
            colliding_cols,
            [f"{c}_orig" for c in colliding_cols],
        )
    exclude_cols = [
        col[0]
        for col in schema
        if col[1].startswith("GEOMETRY")
        or (col[0].endswith("_bbox") and col[1].startswith("STRUCT"))
    ] + colliding_cols
    exclude_sql = ", ".join(f'"{c}"' for c in exclude_cols)
    rename_sql = "".join(f', "{c}" AS "{c}_orig"' for c in colliding_cols)

    # ST_Read tags geometry with source CRS; single-arg ST_Transform infers it.
    # Parquet geometries are untagged (assumed EPSG:4326), so skip transform.
    geom_expr = (
        f"ST_Force2D(ST_Transform(ST_MakeValid(\"{geom_col}\"), 'EPSG:4326'))"
        if geom_type != "GEOMETRY"
        else f'ST_Force2D(ST_MakeValid("{geom_col}"))'
    )

    # Reproject to EPSG:4326 and store as the canonical input table. ST_MakeValid
    # repairs broken ring orientations or self-intersections before transform.
    # ST_Force2D drops any Z/M coordinates that downstream GEOS operations
    # don't handle correctly. Parquet inputs skip ST_Transform (already WGS84).
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_01" AS
        SELECT * EXCLUDE ({exclude_sql}){rename_sql},
               row_number() OVER () AS fid,
               {geom_expr} AS geom
        FROM ({read_expr})
    """)


def read_reproject_and_clean(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Read, reproject, and coverage-clean geodata into table `{name}_01`."""
    read_and_reproject(conn, name, path)

    table = f"{name}_01"
    if not has_valid_topology(conn, table, gap_maximum_width=0):
        logger.info("cleaning coverage: invalid edges or gaps detected")
        coverage_clean(conn, table, table, fids=None)


def export_geometry_table(
    conn: DuckDBPyConnection, table: str, dest: Path, *, exclude_fid: bool = True
) -> None:
    """Export a geometry table to dest, renaming `geom` to `geometry` for output."""
    dest.parent.mkdir(exist_ok=True, parents=True)
    select = "* EXCLUDE (fid)" if exclude_fid else "*"
    conn.execute(f"""--sql
        COPY (
            SELECT {select} RENAME (geom AS geometry) FROM "{table}"
        ) TO '{dest}' {COPY_OPTS[dest.suffix]}
    """)


def export_issues_table(conn: DuckDBPyConnection, table: str, dest: Path) -> None:
    """Export an issues table to dest, or remove any stale file there if it's empty.

    Never writes an empty issues file: a prior run's stale file at dest is
    deleted instead of being left behind looking like unresolved issues.
    """
    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    if count == 0:
        dest.unlink(missing_ok=True)
        return
    export_geometry_table(conn, table, dest, exclude_fid=False)
