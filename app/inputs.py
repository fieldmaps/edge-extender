import logging
import subprocess

from psycopg.sql import SQL, Identifier

from .utils import DATABASE, config

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(
            ST_ReducePrecision(geom, 0.000000001)
        )::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
drop_col = """
    ALTER TABLE {table_attr}
    DROP COLUMN IF EXISTS geom;
"""


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
        ]
    )
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_attr"),
            table_out=Identifier(f"{name}_00"),
        )
    )
    conn.execute(
        SQL(drop_col).format(
            table_attr=Identifier(f"{name}_attr"),
        )
    )
    if config["verbose"].lower() in ("yes", "on", "true", "1"):
        logger.info(name)
