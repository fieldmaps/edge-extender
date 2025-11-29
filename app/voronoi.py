from typing import LiteralString

from psycopg import Connection
from psycopg.sql import SQL, Identifier

from .topology import check_gaps, check_overlaps

query_1: LiteralString = """
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
query_2: LiteralString = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT DISTINCT ON (geom)
        a.fid,
        b.geom
    FROM {table_in1} AS a
    JOIN {table_in2} AS b
    ON ST_DWithin(a.geom, b.geom, 0);
"""
query_3: LiteralString = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(
            ST_Union(geom)
        )::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in}
    GROUP BY fid;
"""
query_4: LiteralString = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        fid,
        ST_Multi(ST_MakeValid(
            ST_CoverageClean(geom) OVER ()
        ))::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_5: LiteralString = """
    SELECT EXISTS(
        SELECT 1
        FROM {table_in} a
        JOIN {table_in} b
        ON ST_Overlaps(a.geom, b.geom)
        WHERE a.fid != b.fid
    );
"""
query_6: LiteralString = """
    SELECT ST_NumInteriorRings(ST_Union(geom))
    FROM {table_in};
"""
drop_tmp: LiteralString = """
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
    DROP TABLE IF EXISTS {table_tmp3};
"""


def main(conn: Connection, name: str, *_: list) -> None:
    """Create Voronoi polygons from points."""
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_03"),
            table_out=Identifier(f"{name}_04_tmp1"),
        ),
    )
    conn.execute(
        SQL(query_2).format(
            table_in1=Identifier(f"{name}_03"),
            table_in2=Identifier(f"{name}_04_tmp1"),
            table_out=Identifier(f"{name}_04_tmp2"),
        ),
    )
    conn.execute(
        SQL(query_3).format(
            table_in=Identifier(f"{name}_04_tmp2"),
            table_out=Identifier(f"{name}_04_tmp3"),
        ),
    )
    check_overlaps(conn, name, f"{name}_04_tmp3")
    conn.execute(
        SQL(query_4).format(
            table_in=Identifier(f"{name}_04_tmp3"),
            table_out=Identifier(f"{name}_04"),
        ),
    )
    check_gaps(conn, name, f"{name}_04")
    conn.execute(
        SQL(drop_tmp).format(
            table_tmp1=Identifier(f"{name}_04_tmp1"),
            table_tmp2=Identifier(f"{name}_04_tmp2"),
            table_tmp3=Identifier(f"{name}_04_tmp3"),
        ),
    )
