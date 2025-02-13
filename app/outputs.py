import logging
import subprocess
from pathlib import Path
from time import sleep

from psycopg.sql import SQL, Identifier

from .utils import DATABASE, config

logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
outputs = cwd / "../outputs"

query_1 = """
    DROP VIEW IF EXISTS {table_out};
    CREATE VIEW {table_out} AS
    SELECT
        a.geom,
        b.*
    FROM {table_in1} AS a
    LEFT JOIN {table_in2} AS b
    ON a.fid = b.fid;
"""


def main(conn, name, file, layer, *_):
    outputs.mkdir(exist_ok=True, parents=True)
    conn.execute(
        SQL(query_1).format(
            table_in1=Identifier(f"{name}_05"),
            table_in2=Identifier(f"{name}_attr"),
            table_out=Identifier(f"{name}_06"),
        )
    )
    shp = ["-lco", "ENCODING=UTF-8"] if file.suffix == ".shp" else []
    parquet = (
        [
            *["-lco", "COMPRESSION=ZSTD"],
            *["-lco", "GEOMETRY_ENCODING=GEOARROW"],
            *["-lco", "GEOMETRY_NAME=geometry"],
        ]
        if file.suffix == ".parquet"
        else []
    )
    output_path = outputs / file.name
    args = (
        [
            "ogr2ogr",
            "-makevalid",
            "-overwrite",
            *["-nln", layer],
            output_path,
            *[f"PG:dbname={DATABASE}", f"{name}_06"],
        ]
        + shp
        + parquet
    )
    if file.suffix == ".parquet":
        output_path.unlink(missing_ok=True)
    success = False
    for retry in range(5):
        result = subprocess.run(args, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            success = True
            break
        sleep(retry**2)
    if not success:
        logger.info(f"output fail: {name}")
        raise RuntimeError(f"could not write to output {name}")
    if config["verbose"].lower() in ("yes", "on", "true", "1"):
        logger.info(name)
