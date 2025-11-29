from typing import LiteralString

from psycopg import Connection
from psycopg.sql import SQL, Identifier

query_1: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        ST_Multi(
            ST_Boundary(geom)
        )::GEOMETRY(MultiLineString, 4326) AS geom
    FROM {table_in1}
    UNION ALL
    SELECT
        ST_Multi(
            ST_Boundary(geom)
        )::GEOMETRY(MultiLineString, 4326) AS geom
    FROM {table_in2};
"""
query_2: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        ST_Multi(
            ST_Union(geom)
        )::GEOMETRY(MultiLineString, 4326) AS geom
    FROM {table_in};
"""
query_3: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        NULL AS fid,
        (ST_Dump(
            ST_Polygonize(geom)
        )).geom::GEOMETRY(Polygon, 4326) AS geom
    FROM {table_in};
"""
query_4: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT DISTINCT ON (a.geom)
        b.fid,
        a.geom
    FROM {table_in1} AS a
    LEFT JOIN {table_in2} AS b
    ON ST_DWithin(ST_PointOnSurface(a.geom), b.geom, 0);
"""
query_5: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT DISTINCT ON (a.geom)
        COALESCE(a.fid, b.fid) AS fid,
        a.geom
    FROM {table_in1} AS a
    LEFT JOIN {table_in2} AS b
    ON ST_DWithin(ST_PointOnSurface(a.geom), b.geom, 0);
"""
query_6: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out} CASCADE;
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(
            ST_Union(geom)
        )::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in}
    WHERE fid IS NOT NULL
    GROUP BY fid;
"""
query_7: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_out} CASCADE;
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(ST_MakeValid(
            ST_CoverageClean(geom) OVER ()
        ))::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
drop_tmp: LiteralString = """--sql
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
    DROP TABLE IF EXISTS {table_tmp3};
    DROP TABLE IF EXISTS {table_tmp4};
    DROP TABLE IF EXISTS {table_tmp5};
    DROP TABLE IF EXISTS {table_tmp6};
"""


def main(conn: Connection, name: str, *_: list) -> None:
    """Merge original geometry with extended polygons."""
    conn.execute(
        SQL(query_1).format(
            table_in1=Identifier(f"{name}_01"),
            table_in2=Identifier(f"{name}_04"),
            table_out=Identifier(f"{name}_05_tmp1"),
        ),
    )
    conn.execute(
        SQL(query_2).format(
            table_in=Identifier(f"{name}_05_tmp1"),
            table_out=Identifier(f"{name}_05_tmp2"),
        ),
    )
    conn.execute(
        SQL(query_3).format(
            table_in=Identifier(f"{name}_05_tmp2"),
            table_out=Identifier(f"{name}_05_tmp3"),
        ),
    )
    conn.execute(
        SQL(query_4).format(
            table_in1=Identifier(f"{name}_05_tmp3"),
            table_in2=Identifier(f"{name}_01"),
            table_out=Identifier(f"{name}_05_tmp4"),
        ),
    )
    conn.execute(
        SQL(query_5).format(
            table_in1=Identifier(f"{name}_05_tmp4"),
            table_in2=Identifier(f"{name}_04"),
            table_out=Identifier(f"{name}_05_tmp5"),
        ),
    )
    conn.execute(
        SQL(query_6).format(
            table_in=Identifier(f"{name}_05_tmp5"),
            table_out=Identifier(f"{name}_05_tmp6"),
        ),
    )
    conn.execute(
        SQL(query_7).format(
            table_in=Identifier(f"{name}_05_tmp6"),
            table_out=Identifier(f"{name}_05"),
        ),
    )
    conn.execute(
        SQL(drop_tmp).format(
            table_tmp1=Identifier(f"{name}_05_tmp1"),
            table_tmp2=Identifier(f"{name}_05_tmp2"),
            table_tmp3=Identifier(f"{name}_05_tmp3"),
            table_tmp4=Identifier(f"{name}_05_tmp4"),
            table_tmp5=Identifier(f"{name}_05_tmp5"),
            table_tmp6=Identifier(f"{name}_05_tmp6"),
        ),
    )
