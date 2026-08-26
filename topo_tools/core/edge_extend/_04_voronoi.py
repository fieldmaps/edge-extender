"""Generates Voronoi polygons from boundary points and clips to bounding extent."""

from duckdb import DuckDBPyConnection


def main(conn: DuckDBPyConnection, name: str, *, debug: bool = False) -> None:
    """Create Voronoi polygons from points."""
    # A stable per-point id: a fid can have many boundary points, so
    # completeness below must track individual points, not fids.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_04_tmp0" AS
        SELECT row_number() OVER () AS point_id, fid, geom FROM "{name}_03b"
    """)

    # Voronoi diagram from all input points
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_04_tmp1" AS
        SELECT UNNEST(ST_Dump(
            ST_CollectionExtract(
                ST_VoronoiDiagram(ST_Collect(list(geom))), 3
            )
        )).geom AS geom
        FROM "{name}_04_tmp0"
    """)

    # ST_Intersects (not ST_Within) catches generators landing exactly on a
    # cell boundary; such a point can match multiple cells, so dedupe by point_id.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_04_tmp2" AS
        SELECT a.point_id, a.fid, b.geom
        FROM "{name}_04_tmp0" AS a
        JOIN "{name}_04_tmp1" AS b
        ON ST_Intersects(a.geom, b.geom)
    """)

    point_count = conn.execute(f'SELECT count(*) FROM "{name}_04_tmp0"').fetchall()[0][
        0
    ]
    assigned_count = conn.execute(
        f'SELECT count(DISTINCT point_id) FROM "{name}_04_tmp2"'
    ).fetchall()[0][0]
    if assigned_count < point_count:
        msg = (
            f"Voronoi assignment incomplete: "
            f"{assigned_count}/{point_count} points assigned"
        )
        raise RuntimeError(msg)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03b"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04_tmp0"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04_tmp1"')

    # ST_MakeValid defends against invalid cells from degenerate point
    # configurations: feeding one to ST_Union_Agg segfaults GEOS.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_04" AS
        SELECT fid, ST_Union_Agg(ST_MakeValid(geom)) AS geom
        FROM "{name}_04_tmp2"
        GROUP BY fid
    """)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_04_tmp2"')
