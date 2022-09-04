import logging
import re
import os
import sqlite3
from subprocess import run
from configparser import ConfigParser
from pathlib import Path
from psycopg import connect

DATABASE = 'edge_extender'

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

cwd = Path(__file__).parent
cfg = ConfigParser()
cfg.read(cwd / '../config.ini')
config = cfg['default']
config['processes'] = str(min(os.cpu_count(), int(
    config['processes'] if config['processes'] else os.cpu_count())))
user = cfg['user'] if cfg.has_section('user') else {}


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
    regex = re.compile(r'\((Multi Polygon|Polygon)\)')
    result = run(['ogrinfo', file], capture_output=True)
    return regex.search(str(result.stdout))


def apply_funcs(name, file, layer, segment, snap, *args):
    conn = connect(f'dbname={DATABASE}', autocommit=True)
    for func in args:
        func(conn, name, file, layer, segment, snap)
    conn.close()


def get_config(name):
    if name in user:
        segment, snap, validate = user[name].split(',')
        segment = segment or config['segment']
        snap = snap or config['snap']
        validate = validate or config['validate']
        return {'segment': segment, 'snap': snap, 'validate': validate}
    else:
        return config
