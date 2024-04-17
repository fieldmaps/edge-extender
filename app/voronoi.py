from psycopg.sql import SQL, Identifier

from .utils import get_config, logging

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
    SELECT EXISTS(
        SELECT 1
        FROM {table_in} a
        JOIN {table_in} b
        ON ST_Overlaps(a.geom, b.geom)
        WHERE a.fid != b.fid
    );
"""
query_5 = """
    SELECT ST_NumInteriorRings(ST_Union(geom))
    FROM {table_in};
"""
drop_tmp = """
    DROP TABLE IF EXISTS {table_tmp1};
    DROP TABLE IF EXISTS {table_tmp2};
"""


def check_topology(conn, name):
    has_overlaps = conn.execute(
        SQL(query_4).format(
            table_in=Identifier(f"{name}_04"),
        )
    ).fetchone()[0]
    has_gaps = (
        conn.execute(
            SQL(query_5).format(
                table_in=Identifier(f"{name}_04"),
            )
        ).fetchone()[0]
        > 0
    )
    if has_overlaps or has_gaps:
        overlaps_txt = "OVERLAPS" if has_overlaps else ""
        and_txt = " & " if has_gaps and has_overlaps else ""
        gaps_txt = "GAPS" if has_gaps else ""
        logger.info(f"{overlaps_txt}{and_txt}{gaps_txt}: {name}")
        raise RuntimeError(
            f"{overlaps_txt}{and_txt}{gaps_txt} in voronoi polygons, "
            + "try adjusting segment and/or snap values."
        )


def main(conn, name, __, ___, segment, snap, *_):
    config = get_config(name)
    if segment is not None and snap is not None:
        name = f"{name}_{segment}_{snap}".replace(".", "_")
    conn.execute(
        SQL(query_1).format(
            table_in=Identifier(f"{name}_03"),
            table_out=Identifier(f"{name}_04_tmp1"),
        )
    )
    conn.execute(
        SQL(query_2).format(
            table_in1=Identifier(f"{name}_03"),
            table_in2=Identifier(f"{name}_04_tmp1"),
            table_out=Identifier(f"{name}_04_tmp2"),
        )
    )
    conn.execute(
        SQL(query_3).format(
            table_in=Identifier(f"{name}_04_tmp2"),
            table_out=Identifier(f"{name}_04"),
        )
    )
    conn.execute(
        SQL(drop_tmp).format(
            table_tmp1=Identifier(f"{name}_04_tmp1"),
            table_tmp2=Identifier(f"{name}_04_tmp2"),
        )
    )
    if config["validate"].lower() in ("yes", "on", "true", "1"):
        check_topology(conn, name)
    logger.info(name)
