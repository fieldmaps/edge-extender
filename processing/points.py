from psycopg2 import connect
from psycopg2.sql import SQL, Identifier, Literal
from .utils import config, logging, DATABASE

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        ST_Multi(ST_Union(
            ST_Buffer(ST_Boundary(geom), 0.000000001)
        ))::GEOMETRY(MultiPolygon, 4326) as geom
    FROM {table_in};
"""
query_2 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        a.id,
        (ST_Dump(ST_Union(ST_SnapToGrid(ST_Difference(
            ST_Points(ST_Segmentize(a.geom, {segment})), b.geom
        ), {snap})))).geom::GEOMETRY(Point, 4326) as geom
    FROM {table_in1} as a
    CROSS JOIN {table_in2} as b
    GROUP BY a.id
    UNION ALL
    SELECT
        a.id,
        (ST_Dump(ST_Boundary(
            ST_Difference(a.geom, b.geom)
        ))).geom::GEOMETRY(Point, 4326) as geom
    FROM {table_in1} as a
    CROSS JOIN {table_in2} as b;
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
"""


def main(name, *args):
    con = connect(database=DATABASE)
    cur = con.cursor()
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_01'),
        table_out=Identifier(f'{name}_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in1=Identifier(f'{name}_01'),
        table_in2=Identifier(f'{name}_tmp1'),
        segment=Literal(config['segment']),
        snap=Literal(config['snap']),
        table_out=Identifier(f'{name}_02'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_tmp1'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(name)
