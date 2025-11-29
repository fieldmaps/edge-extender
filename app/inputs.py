import subprocess

from psycopg.sql import SQL, Identifier

from .utils import DATABASE

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT *
    FROM {table_in};
"""
query_2 = """
    ALTER TABLE {table_attr}
    DROP COLUMN IF EXISTS geom;
"""


def main(conn, name, file, layer, *_):
    subprocess.run(
        [
            *["gdal", "vector", "pipeline"],
            *["read", file, f"--input-layer={layer}", "!"],
            *["clean-coverage", "!"],
            *["make-valid", "!"],
            *["set-geom-type", "--multi", "--dim=XY", "!"],
            *["reproject", "--dst-crs=EPSG:4326", "!"],
            *["write", f"PG:dbname={DATABASE}"],
            "--quiet",
            "--overwrite-layer",
            "--output-format=PostgreSQL",
            f"--output-layer={name}_01",
            "--layer-creation-option=FID=fid",
            "--layer-creation-option=GEOMETRY_NAME=geom",
            "--layer-creation-option=LAUNDER=NO",
        ],
        check=False,
    )
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_01"),
            table_out=Identifier(f"{name}_attr"),
        ),
    )
    conn.execute(
        SQL(query_2).format(
            table_attr=Identifier(f"{name}_attr"),
        ),
    )
