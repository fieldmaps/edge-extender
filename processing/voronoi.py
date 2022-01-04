from psycopg2.sql import SQL, Identifier
from .utils import logging, get_config

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
    SELECT DISTINCT ON (geom)
        a.fid,
        b.geom
    FROM {table_in1} AS a
    JOIN {table_in2} AS b
    ON ST_DWithin(a.geom, b.geom, 0);
"""
query_3 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_MakePolygon(ST_ExteriorRing(
            (ST_Dump(ST_Union(
                ST_ReducePrecision(geom, 0.000000001)
            ))).geom
        ))::GEOMETRY(Polygon, 4326) AS geom
    FROM {table_in}
    GROUP BY fid;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_4 = """
    SELECT ST_NumInteriorRings(ST_Union(geom))
    FROM {table_in};
"""
query_5 = """
    SELECT EXISTS(
        SELECT 1
        FROM {table_in} a
        JOIN {table_in} b
        ON ST_Overlaps(a.geom, b.geom)
        WHERE a.fid != b.fid
    );
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
"""


def check_topology(cur, name):
    cur.execute(SQL(query_4).format(
        table_in=Identifier(f'{name}_04'),
    ))
    has_gaps = cur.fetchone()[0] > 0
    cur.execute(SQL(query_5).format(
        table_in=Identifier(f'{name}_04'),
    ))
    has_overlaps = cur.fetchone()[0]
    if has_gaps or has_overlaps:
        gaps_txt = f'GAPS' if has_gaps else ''
        and_txt = f' & ' if has_gaps and has_overlaps else ''
        overlaps_txt = f'OVERLAPS' if has_overlaps else ''
        logger.info(f'{gaps_txt}{and_txt}{overlaps_txt}: {name}')
        raise RuntimeError(
            f'{gaps_txt}{and_txt}{overlaps_txt} in voronoi polygons, ' +
            'try adjusting segment and/or snap values.')


def main(cur, name, *_):
    config = get_config(name)
    cur.execute(SQL(query_1).format(
        table_in=Identifier(f'{name}_03'),
        table_out=Identifier(f'{name}_04_tmp1'),
    ))
    cur.execute(SQL(query_2).format(
        table_in1=Identifier(f'{name}_03'),
        table_in2=Identifier(f'{name}_04_tmp1'),
        table_out=Identifier(f'{name}_04_tmp2'),
    ))
    cur.execute(SQL(query_3).format(
        table_in=Identifier(f'{name}_04_tmp2'),
        table_out=Identifier(f'{name}_04'),
    ))
    cur.execute(SQL(drop_tmp).format(
        table_tmp1=Identifier(f'{name}_04_tmp1'),
        table_tmp2=Identifier(f'{name}_04_tmp2'),
    ))
    if config['validate'].lower() in ('yes', 'on', 'true', '1'):
        check_topology(cur, name)
    logger.info(name)
