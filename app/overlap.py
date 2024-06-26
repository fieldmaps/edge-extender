import logging

from psycopg.sql import SQL, Identifier

from .utils import get_config

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        ST_Multi(
            ST_Union(ST_Boundary(geom))
        )::GEOMETRY(MultiLineString, 4326) AS geom
    FROM {table_in};
"""
query_2 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        NULL AS fid,
        (ST_Dump(
            ST_Polygonize(geom)
        )).geom::GEOMETRY(Polygon, 4326) AS geom
    FROM {table_in};
"""
query_3 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        b.fid,
        a.geom
    FROM {table_in1} AS a
    LEFT JOIN {table_in2} AS b
    ON ST_DWithin(ST_PointOnSurface(a.geom), b.geom, 0);
"""
query_4 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT DISTINCT ON (geom)
        fid, geom
    FROM {table_in};
"""
query_5 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(
            ST_Union(geom)
        )::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in}
    WHERE fid IS NOT NULL
    GROUP BY fid;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_6 = """
    SELECT count(*)
    FROM {table_in};
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
    DROP TABLE IF EXISTS {table_tmp3};
    DROP TABLE IF EXISTS {table_tmp4};
"""


def check_topology(conn, name):
    rows_org = conn.execute(
        SQL(query_6).format(table_in=Identifier(f"{name}_00"))
    ).fetchone()[0]
    rows_new = conn.execute(
        SQL(query_6).format(table_in=Identifier(f"{name}_01"))
    ).fetchone()[0]
    if rows_org != rows_new:
        logger.info(f"{rows_new} of {rows_org}: {name}")
        raise RuntimeError(
            f"{rows_new} of {rows_org} input polygons, "
            + "remove overlapping polygons."
        )


def main(conn, name, *_):
    config = get_config(name)
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_00"),
            table_out=Identifier(f"{name}_01_tmp1"),
        )
    )
    conn.execute(
        SQL(query_2).format(
            table_in=Identifier(f"{name}_01_tmp1"),
            table_out=Identifier(f"{name}_01_tmp2"),
        )
    )
    conn.execute(
        SQL(query_3).format(
            table_in1=Identifier(f"{name}_01_tmp2"),
            table_in2=Identifier(f"{name}_00"),
            table_out=Identifier(f"{name}_01_tmp3"),
        )
    )
    conn.execute(
        SQL(query_4).format(
            table_in=Identifier(f"{name}_01_tmp3"),
            table_out=Identifier(f"{name}_01_tmp4"),
        )
    )
    conn.execute(
        SQL(query_5).format(
            table_in=Identifier(f"{name}_01_tmp4"),
            table_out=Identifier(f"{name}_01"),
        )
    )
    conn.execute(
        SQL(drop_tmp).format(
            table_tmp1=Identifier(f"{name}_01_tmp1"),
            table_tmp2=Identifier(f"{name}_01_tmp2"),
            table_tmp3=Identifier(f"{name}_01_tmp3"),
            table_tmp4=Identifier(f"{name}_01_tmp4"),
        )
    )
    if config["validate"].lower() in ("yes", "on", "true", "1"):
        check_topology(conn, name)
    if config["verbose"].lower() in ("yes", "on", "true", "1"):
        logger.info(name)
