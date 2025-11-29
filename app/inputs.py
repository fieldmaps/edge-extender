from pathlib import Path
from subprocess import CalledProcessError, run
from typing import LiteralString

from psycopg import Connection
from psycopg.sql import SQL, Identifier

from .utils import DATABASE

query_1: LiteralString = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(ST_MakeValid(
            ST_CoverageClean(
                ST_Transform(
                    ST_Force2D(geom), 4326
                )
            ) OVER ()
        ))::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
"""
query_2: LiteralString = """
    ALTER TABLE {table_attr}
    DROP COLUMN IF EXISTS geom;
"""


def gdal_import(name: str, file: Path, layer: str, args: list[str]) -> None:
    """Import geodata into PostGIS."""
    run(
        [
            *["gdal", "vector", *args],
            *[file, f"PG:dbname={DATABASE}"],
            "--multi",
            "--overwrite-layer",
            "--output-format=PostgreSQL",
            f"--input-layer={layer}",
            f"--output-layer={name}_attr",
            "--layer-creation-option=FID=fid",
            "--layer-creation-option=GEOMETRY_NAME=geom",
            "--layer-creation-option=GEOM_TYPE=geometry",
            "--layer-creation-option=LAUNDER=NO",
        ],
        check=True,
        capture_output=True,
    )


def main(conn: Connection, name: str, file: Path, layer: str, *_: list) -> None:
    """Import geodata into PostGIS with topology cleaning."""
    try:
        gdal_import(name, file, layer, ["set-geom-type", "--quiet"])
    except CalledProcessError:
        gdal_import(name, file, layer, ["geom", "set-type"])
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_attr"),
            table_out=Identifier(f"{name}_01"),
        ),
    )
    conn.execute(
        SQL(query_2).format(
            table_attr=Identifier(f"{name}_attr"),
        ),
    )
