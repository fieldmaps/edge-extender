import logging
import subprocess
from pathlib import Path
from psycopg2 import connect
from psycopg2.sql import SQL, Identifier
from .utils import config

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
outputs = (cwd / '../outputs').resolve()
outputs.mkdir(exist_ok=True, parents=True)


def main(name, file, layer):
    logger.info(f'Starting {name}')
    con = connect(database='polygon_voronoi')
    cur = con.cursor()
    query_1 = """
        DROP VIEW IF EXISTS {table_out};
        CREATE VIEW {table_out} AS
        SELECT DISTINCT ON (b.{id})
            a.geom,
            b.*
        FROM {table_in1} as a
        LEFT JOIN {table_in2} as b
        ON a.id = b.{id};
    """
    cur.execute(SQL(query_1).format(
        id=Identifier(f"{config['dissolve']}"),
        table_in1=Identifier(f'{name}_04'),
        table_in2=Identifier(f'{name}_attr'),
        table_out=Identifier(f'{name}_05'),
    ))
    con.commit()
    cur.close()
    con.close()
    shp = ['-lco', 'ENCODING=UTF-8'] if file.suffix == '.shp' else []
    subprocess.run([
        'ogr2ogr',
        '-overwrite',
        '-nln', layer,
        (outputs / file.name).resolve(),
        'PG:dbname=polygon_voronoi', f'{name}_05',
    ] + shp)
    logger.info(f'Finished {name}')
