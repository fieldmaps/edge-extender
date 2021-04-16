from psycopg2 import connect
from psycopg2.sql import SQL, Identifier
from .utils import logging

logger = logging.getLogger(__name__)


def main(name, *args):
    con = connect(database='polygon_voronoi')
    cur = con.cursor()
    query_1 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            (ST_Dump(
                ST_VoronoiPolygons(ST_Collect(geom))
            )).geom::GEOMETRY(Polygon, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_2 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            (ST_Dump(
                ST_CollectionExtract(ST_MakeValid(geom), 3)
            )).geom::GEOMETRY(Polygon, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_3 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            a.id,
            ST_Multi(
                ST_Union(b.geom)
            )::GEOMETRY(MultiPolygon, 4326) as geom
        FROM {table_in1} as a
        JOIN {table_in2} as b
        ON ST_Intersects(a.geom, b.geom)
        GROUP BY a.id;
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    drop_tmp = """
        DROP TABLE IF EXISTS {table_tmp1};
        DROP TABLE IF EXISTS {table_tmp2};
    """
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_02'),
        table_out=Identifier(f'{name}_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in=Identifier(f'{name}_tmp1'),
        table_out=Identifier(f'{name}_tmp2'),
    ))
    cur.execute(SQL(query_3).format(
        table_in1=Identifier(f'{name}_02'),
        table_in2=Identifier(f'{name}_tmp2'),
        table_out=Identifier(f'{name}_03'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_tmp1'),
        table_tmp2=Identifier(f'{name}_tmp2'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(name)
