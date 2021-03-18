import logging
import subprocess
from pathlib import Path
from psycopg2 import connect
from psycopg2.sql import SQL, Identifier

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
inputs = (cwd / '../inputs').resolve()


def main(name):
    logger.info(f'Starting {name}')
    con = connect(database='polygon_voronoi')
    cur = con.cursor()
    subprocess.run([
        'ogr2ogr',
        '-overwrite',
        '-nln', f'{name}_tmp1',
        '-f', 'PostgreSQL', 'PG:dbname=polygon_voronoi',
        (inputs / f'{name}.gpkg').resolve(),
    ])
    query_1 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            id,
            ST_Transform(ST_Multi(ST_Union(
                ST_Force2D(ST_MakeValid(geom))
            )), 4326)::GEOMETRY(MultiPolygon, 4326) as geom
        FROM {table_in}
        GROUP BY id;
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    drop_tmp = """
        DROP TABLE IF EXISTS {table_tmp1};
    """
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_tmp1'),
        table_out=Identifier(f'{name}_00'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_tmp1'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(f'Finished {name}')
