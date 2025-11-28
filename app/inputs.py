import subprocess
from venv import logger

from psycopg.sql import SQL, Identifier

from .utils import DATABASE

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(
            ST_CoverageClean(geom) OVER ()
        )::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_2 = """
    SELECT count(*)
    FROM {table_in};
"""
drop_col = """
    ALTER TABLE {table_attr}
    DROP COLUMN IF EXISTS geom;
"""


def check_dropped_polygons(conn, name):
    rows_org = conn.execute(
        SQL(query_2).format(table_in=Identifier(f"{name}_attr")),
    ).fetchone()[0]
    rows_new = conn.execute(
        SQL(query_2).format(table_in=Identifier(f"{name}_01")),
    ).fetchone()[0]
    if rows_org != rows_new:
        logger.error(f"{rows_new} of {rows_org}: {name}")
        raise RuntimeError(
            f"{rows_new} of {rows_org} input polygons, remove overlapping polygons.",
        )


def main(conn, name, file, layer, *_):
    subprocess.run(
        [
            "ogr2ogr",
            "-makevalid",
            "-overwrite",
            *["--config", "OGR_GEOJSON_MAX_OBJ_SIZE", "0"],
            *["-dim", "XY"],
            *["-t_srs", "EPSG:4326"],
            *["-lco", "FID=fid"],
            *["-lco", "GEOMETRY_NAME=geom"],
            *["-lco", "LAUNDER=NO"],
            *["-lco", "SPATIAL_INDEX=NONE"],
            *["-nlt", "PROMOTE_TO_MULTI"],
            *["-nln", f"{name}_attr"],
            *["-f", "PostgreSQL", f"PG:dbname={DATABASE}"],
            *[file, layer],
        ],
        check=False,
    )
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_attr"),
            table_out=Identifier(f"{name}_01"),
        ),
    )
    conn.execute(
        SQL(drop_col).format(
            table_attr=Identifier(f"{name}_attr"),
        ),
    )
    check_dropped_polygons(conn, name)
