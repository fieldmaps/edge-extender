import logging
import re
import sqlite3
from configparser import ConfigParser
from multiprocessing import cpu_count
from os import environ
from pathlib import Path
from subprocess import run

from psycopg import connect

DATABASE = "app"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("postgres").setLevel(logging.WARNING)

environ["OGR_GEOJSON_MAX_OBJ_SIZE"] = "0"

cwd = Path(__file__).parent
cfg = ConfigParser()
cfg.read(cwd / "../config.ini")
config = cfg["default"]
config["processes"] = str(
    min(cpu_count(), int(config["processes"] if config["processes"] else cpu_count())),
)
user = cfg["user"] if cfg.has_section("user") else {}

truthy = ("yes", "on", "true", "1")


def get_gpkg_layers(file: Path) -> list[str]:
    """Get list of layers in GeoPackage."""
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


def is_polygon(file: Path) -> bool:
    """Check if file is a polygon."""
    regex = re.compile(r"\((Multi Polygon|Polygon)\)")
    result = run(["ogrinfo", file], check=False, capture_output=True)
    return bool(regex.search(str(result.stdout)))


def apply_funcs(name: str, file: Path, layer: str, *args: list) -> None:
    """Apply functions to database."""
    conn = connect(f"dbname={DATABASE}", autocommit=True)
    for func in args:
        func(conn, name, file, layer)
    conn.close()


def get_config(name: str) -> dict[str, str]:
    """Get configuration settings for a file."""
    name = name.split("_")[0]
    if name in user:
        segment, snap = user[name].split(",")
        segment = segment or config["segment"]
        snap = snap or config["snap"]
        return {"segment": segment, "snap": snap}
    return dict(config)
