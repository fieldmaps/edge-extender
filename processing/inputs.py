import subprocess
from psycopg2 import connect
from psycopg2.sql import SQL, Identifier
from .utils import logging, DATABASE

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Transform(ST_Multi(
            ST_Force2D(ST_SnapToGrid(geom, 0.000000001))
        ), 4326)::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
drop_tmp = """
    ALTER TABLE {table_attr}
    DROP COLUMN IF EXISTS geom;
"""


def main(name, file, layer):
    subprocess.run([
        'ogr2ogr',
        '-makevalid',
        '-overwrite',
        '--config', 'OGR_GEOJSON_MAX_OBJ_SIZE', '2048MB',
        '-lco', 'FID=fid',
        '-lco', 'GEOMETRY_NAME=geom',
        '-lco', 'LAUNDER=NO',
        '-lco', 'SPATIAL_INDEX=NONE',
        '-nlt', 'PROMOTE_TO_MULTI',
        '-nln', f'{name}_attr',
        '-f', 'PostgreSQL', f'PG:dbname={DATABASE}',
        file, layer,
    ])
    con = connect(database=DATABASE)
    cur = con.cursor()
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_attr'),
        table_out=Identifier(f'{name}_00'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_attr=Identifier(f'{name}_attr'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(name)
