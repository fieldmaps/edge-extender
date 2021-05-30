from psycopg2.sql import SQL, Identifier
from .utils import logging

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        (ST_Dump(
            ST_CollectionExtract(ST_MakeValid(
                ST_VoronoiPolygons(ST_Collect(geom))
            ), 3)
        )).geom::GEOMETRY(Polygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_2 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        a.fid,
        ST_MakePolygon(ST_ExteriorRing(
            (ST_Dump(ST_Union(b.geom))).geom
        ))::GEOMETRY(Polygon, 4326) AS geom
    FROM {table_in1} AS a
    JOIN {table_in2} AS b
    ON ST_Within(a.geom, b.geom)
    GROUP BY a.fid;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
"""


def main(cur, name, *_):
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_02'),
        table_out=Identifier(f'{name}_03_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in1=Identifier(f'{name}_02'),
        table_in2=Identifier(f'{name}_03_tmp1'),
        table_out=Identifier(f'{name}_03'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_03_tmp1'),
    ))
    logger.info(name)
