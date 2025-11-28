import logging
import re
import sqlite3
from configparser import ConfigParser
from multiprocessing import cpu_count
from pathlib import Path
from subprocess import run

from psycopg import connect

DATABASE = "app"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

cwd = Path(__file__).parent
cfg = ConfigParser()
cfg.read(cwd / "../config.ini")
config = cfg["default"]
config["processes"] = str(
    min(cpu_count(), int(config["processes"] if config["processes"] else cpu_count())),
)
user = cfg["user"] if cfg.has_section("user") else {}


def get_gpkg_layers(file):
    query = """
        SELECT table_name, geometry_type_name
        FROM gpkg_geometry_columns
        WHERE geometry_type_name IN ('POLYGON', 'MULTIPOLYGON', 'GEOMETRY');
    """
    con = sqlite3.connect(file)
    cur = con.cursor()
    layers = sorted([row[0] for row in cur.execute(query)])
    cur.close()
    con.close()
    return layers


def is_polygon(file):
    regex = re.compile(r"\((Multi Polygon|Polygon)\)")
    result = run(["gdal", "info", "--summary", file], check=False, capture_output=True)
    return regex.search(str(result.stdout))


def apply_funcs(name, file, layer, *args):
    conn = connect(f"dbname={DATABASE}", autocommit=True)
    for func in args:
        func(conn, name, file, layer)
    conn.close()


def get_config(name):
    name = name.split("_")[0]
    if name in user:
        segment, snap = user[name].split(",")
        segment = segment or config["segment"]
        snap = snap or config["snap"]
        return {"segment": segment, "snap": snap}
    return config
