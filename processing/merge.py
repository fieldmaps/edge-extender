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
            ST_Multi(
                ST_Boundary(geom)
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in1}
        UNION ALL
        SELECT
            ST_Multi(
                ST_Boundary(geom)
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in2};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_2 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            ST_Multi(
                ST_Union(geom)
            )::GEOMETRY(MultiLineString, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_3 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            NULL as id,
            (ST_Dump(
                ST_Polygonize(geom))
            ).geom::GEOMETRY(Polygon, 4326) as geom
        FROM {table_in};
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_4 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            b.id,
            a.geom
        FROM {table_in1} as a
        LEFT JOIN {table_in2} as b
        ON ST_Within(ST_Buffer(a.geom, -0.000000001), b.geom);
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_5 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            COALESCE(a.id, b.id) as id,
            a.geom
        FROM {table_in1} as a
        LEFT JOIN {table_in2} as b
        ON ST_Within(ST_Buffer(a.geom, -0.000000001), b.geom);
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    query_6 = """
        DROP TABLE IF EXISTS {table_out};
        CREATE TABLE {table_out} AS
        SELECT
            id,
            ST_Multi(
                ST_Union(geom)
            )::GEOMETRY(MultiPolygon, 4326) as geom
        FROM {table_in}
        WHERE id IS NOT NULL
        GROUP BY id;
        CREATE INDEX ON {table_out} USING GIST(geom);
    """
    drop_tmp = """
        DROP TABLE IF EXISTS {table_tmp1};
        DROP TABLE IF EXISTS {table_tmp2};
        DROP TABLE IF EXISTS {table_tmp3};
        DROP TABLE IF EXISTS {table_tmp4};
        DROP TABLE IF EXISTS {table_tmp5};
    """
    cur.execute(SQL(query_1).format(
        table_in1=Identifier(f'{name}_00'),
        table_in2=Identifier(f'{name}_03'),
        table_out=Identifier(f'{name}_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in=Identifier(f'{name}_tmp1'),
        table_out=Identifier(f'{name}_tmp2'),
    ))
    cur.execute(SQL(query_3).format(
        table_in=Identifier(f'{name}_tmp2'),
        table_out=Identifier(f'{name}_tmp3'),
    ))
    cur.execute(SQL(query_4).format(
        table_in1=Identifier(f'{name}_tmp3'),
        table_in2=Identifier(f'{name}_00'),
        table_out=Identifier(f'{name}_tmp4'),
    ))
    cur.execute(SQL(query_5).format(
        table_in1=Identifier(f'{name}_tmp4'),
        table_in2=Identifier(f'{name}_03'),
        table_out=Identifier(f'{name}_tmp5'),
    ))
    cur.execute(SQL(query_6).format(
        table_in=Identifier(f'{name}_tmp5'),
        table_out=Identifier(f'{name}_04'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_tmp1'),
        table_tmp2=Identifier(f'{name}_tmp2'),
        table_tmp3=Identifier(f'{name}_tmp3'),
        table_tmp4=Identifier(f'{name}_tmp4'),
        table_tmp5=Identifier(f'{name}_tmp5'),
    ))
    con.commit()
    cur.close()
    con.close()
    logger.info(f'Finished {name}')
