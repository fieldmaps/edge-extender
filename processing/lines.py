import logging
from psycopg2 import connect
from psycopg2.sql import SQL, Identifier

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)


def main(name, *args):
    logger.info(f'Starting {name}')
    con = connect(database='polygon_voronoi')
    cur = con.cursor()
    query_1 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            id,
            ST_Multi(
                ST_Boundary(geom)
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_2 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            ST_Multi(
                ST_Boundary(ST_Union(geom))
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_3 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            a.id,
            ST_Multi(
                ST_CollectionExtract(ST_Intersection(a.geom, b.geom), 2)
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in1} as a
        JOIN {table_in2} as b
        ON ST_Intersects(a.geom, b.geom);
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    drop_tmp = """
        DROP TABLE IF EXISTS {table_tmp1};
        DROP TABLE IF EXISTS {table_tmp2};
    """
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_00'),
        table_out=Identifier(f'{name}_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in=Identifier(f'{name}_00'),
        table_out=Identifier(f'{name}_tmp2'),
    ))
    cur.execute(SQL(query_3).format(
        table_in1=Identifier(f'{name}_tmp1'),
        table_in2=Identifier(f'{name}_tmp2'),
        table_out=Identifier(f'{name}_01'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_tmp1'),
        table_tmp2=Identifier(f'{name}_tmp2'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(f'Finished {name}')
