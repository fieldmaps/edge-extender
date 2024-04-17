from psycopg.sql import SQL, Identifier, Literal

from .utils import get_config, logging

logger = logging.getLogger(__name__)

query_1 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        ST_Multi(ST_Union(
            ST_Buffer(ST_Boundary(geom), 0.000000001)
        ))::GEOMETRY(MultiPolygon, 4326) AS geom
    FROM {table_in};
"""
query_2 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        a.fid,
        (ST_Dump(
            ST_Union(ST_SnapToGrid(
                ST_Difference(ST_Points(
                    ST_Segmentize(a.geom, {segment})
                ), b.geom)
            , {snap}))
        )).geom::GEOMETRY(Point, 4326) AS geom
    FROM {table_in1} AS a
    CROSS JOIN {table_in2} AS b
    GROUP BY a.fid
    UNION ALL
    SELECT
        a.fid,
        (ST_Dump(
            ST_Boundary(ST_Difference(a.geom, b.geom))
        )).geom::GEOMETRY(Point, 4326) AS geom
    FROM {table_in1} AS a
    CROSS JOIN {table_in2} AS b;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_3 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT
        geom,
        count(*)
    FROM {table_in}
    GROUP BY geom;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
query_4 = """
    DROP TABLE IF EXISTS {table_out};
    CREATE TABLE {table_out} AS
    SELECT DISTINCT ON (a.geom)
        b.fid,
        a.geom
    FROM {table_in1} AS a
    LEFT JOIN {table_in2} AS b
    ON a.geom = b.geom
    WHERE a.count = 1;
    CREATE INDEX ON {table_out} USING GIST(geom);
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
    DROP TABLE IF EXISTS {table_tmp3};
"""


def main(conn, name_0, file, ___, segment, snap, *_):
    config = get_config(file.stem)
    name = name_0
    if segment is not None and snap is not None:
        name = f"{name_0}_{segment}_{snap}".replace(".", "_")
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name_0}_02"),
            table_out=Identifier(f"{name}_03_tmp1"),
        )
    )
    conn.execute(
        SQL(query_2).format(
            table_in1=Identifier(f"{name_0}_02"),
            table_in2=Identifier(f"{name}_03_tmp1"),
            segment=Literal(segment or config["segment"]),
            snap=Literal(snap or config["snap"]),
            table_out=Identifier(f"{name}_03_tmp2"),
        )
    )
    conn.execute(
        SQL(query_3).format(
            table_in=Identifier(f"{name}_03_tmp2"),
            table_out=Identifier(f"{name}_03_tmp3"),
        )
    )
    conn.execute(
        SQL(query_4).format(
            table_in1=Identifier(f"{name}_03_tmp3"),
            table_in2=Identifier(f"{name}_03_tmp2"),
            table_out=Identifier(f"{name}_03"),
        )
    )
    conn.execute(
        SQL(drop_tmp).format(
            table_tmp1=Identifier(f"{name}_03_tmp1"),
            table_tmp2=Identifier(f"{name}_03_tmp2"),
            table_tmp3=Identifier(f"{name}_03_tmp3"),
        )
    )
    logger.info(name)
