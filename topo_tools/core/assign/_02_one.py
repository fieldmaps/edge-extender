"""Assigns each (already-extended) child to the parent it shares the most area with."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.clip import subdivide_boundary
from topo_tools.core.constants import CLIP_TILE_MIN_VERTICES, EQUAL_AREA_CRS
from topo_tools.core.duckdb_utils import bbox_columns_sql

logger = getLogger(__name__)


def prepare_parent_tiles(conn: DuckDBPyConnection, name: str) -> None:
    """Precompute the parent's part/tile decomposition, independent of any children.

    A caller processing many children files against one unchanging parent
    (api.clip._clip_each_file()) calls this once and passes
    use_cached_tiles=True to every main()/_build_pairs() call afterward,
    instead of re-tiling the same high-vertex parent parts on every file.
    """
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_parent_parts" AS
        WITH parts AS (
            SELECT fid, UNNEST(ST_Dump(geom)).geom AS part_geom FROM "{name}_parent_01"
        )
        SELECT row_number() OVER () AS part_id, fid, part_geom,
               ST_NPoints(part_geom) AS n_points, {bbox_columns_sql("part_geom")}
        FROM parts
    """)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_parent_tiles" (
            parent_fid BIGINT, geom GEOMETRY,
            xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE
        )
    """)
    heavy_parts = conn.execute(f"""--sql
        SELECT part_id, fid FROM "{name}_02_parent_parts"
        WHERE n_points >= {CLIP_TILE_MIN_VERTICES}
    """).fetchall()
    if heavy_parts:
        logger.info(
            "assign-one: tiling %d heavy parent part(s) (>= %d vertices)",
            len(heavy_parts),
            CLIP_TILE_MIN_VERTICES,
        )
    for part_id, parent_fid in heavy_parts:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE "{name}_02_heavy_src" AS
            SELECT part_geom AS geom FROM "{name}_02_parent_parts"
            WHERE part_id = {part_id}
        """)
        subdivide_boundary(
            conn, f"{name}_02_heavy_src", "geom", f"{name}_02_heavy_tiles_raw"
        )
        conn.execute(f"""--sql
            INSERT INTO "{name}_02_parent_tiles" BY NAME
            SELECT {parent_fid} AS parent_fid, geom, {bbox_columns_sql("geom")}
            FROM "{name}_02_heavy_tiles_raw"
        """)
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_heavy_src"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_heavy_tiles_raw"')


def _build_pairs(
    conn: DuckDBPyConnection, name: str, *, use_cached_tiles: bool = False
) -> None:
    """Bbox-prefiltered overlap-area join, tiling any oversized parent part first.

    A parent part at or above CLIP_TILE_MIN_VERTICES is grid-tiled before
    intersecting, instead of one ST_Intersection call against the whole thing.
    use_cached_tiles=True skips that tiling, reusing whatever a prior
    prepare_parent_tiles() call already left in {name}_02_parent_parts/
    {name}_02_parent_tiles.
    """
    if not use_cached_tiles:
        prepare_parent_tiles(conn, name)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_tmp1" AS
        WITH parts AS (
            SELECT fid, UNNEST(ST_Dump(geom)).geom AS part_geom FROM "{name}_child_01"
        )
        SELECT fid, part_geom, {bbox_columns_sql("part_geom")}
        FROM parts
    """)

    # Parent parts below the tiling threshold: exact intersection directly.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_pairs_raw" AS
        SELECT c.fid AS child_fid, p.fid AS parent_fid,
               SUM(ST_Area(ST_Transform(
                   ST_Intersection(c.part_geom, p.part_geom),
                   'EPSG:4326', '{EQUAL_AREA_CRS}'
               ))) AS shared_area
        FROM "{name}_02_tmp1" c
        JOIN "{name}_02_parent_parts" p
          ON p.xmax >= c.xmin AND p.xmin <= c.xmax
         AND p.ymax >= c.ymin AND p.ymin <= c.ymax
         AND ST_Intersects(c.part_geom, p.part_geom)
        WHERE p.n_points < {CLIP_TILE_MIN_VERTICES}
        GROUP BY c.fid, p.fid
    """)

    # Oversized parent parts: children joined to the precomputed tile set at
    # once, tiles already tagged with their own parent_fid.
    conn.execute(f"""--sql
        INSERT INTO "{name}_02_pairs_raw"
        SELECT c.fid AS child_fid, t.parent_fid AS parent_fid,
               SUM(ST_Area(ST_Transform(
                   ST_Intersection(c.part_geom, t.geom),
                   'EPSG:4326', '{EQUAL_AREA_CRS}'
               ))) AS shared_area
        FROM "{name}_02_tmp1" c
        JOIN "{name}_02_parent_tiles" t
          ON t.xmax >= c.xmin AND t.xmin <= c.xmax
         AND t.ymax >= c.ymin AND t.ymin <= c.ymax
         AND ST_Intersects(c.part_geom, t.geom)
        GROUP BY c.fid, t.parent_fid
    """)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_pairs" AS
        SELECT child_fid, parent_fid, SUM(shared_area) AS shared_area
        FROM "{name}_02_pairs_raw"
        GROUP BY child_fid, parent_fid
    """)

    drop_tables = ["_02_tmp1", "_02_pairs_raw"]
    if not use_cached_tiles:
        drop_tables += ["_02_parent_parts", "_02_parent_tiles"]
    for tbl in drop_tables:
        conn.execute(f'DROP TABLE IF EXISTS "{name}{tbl}"')


def main(
    conn: DuckDBPyConnection, name: str, *, use_cached_tiles: bool = False
) -> None:
    """Force every child in a source_file onto that file's single majority-vote parent.

    A file's children are one group (e.g. one country's admin2 units), not
    independently routed to whichever parent each one individually overlaps
    most, guards against already-extended/overshoot geometry crossing
    borders. Every child in one file lands on one shared parent.
    """
    _build_pairs(conn, name, use_cached_tiles=use_cached_tiles)

    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_file_votes" AS
        SELECT c.source_file, pr.parent_fid, COUNT(DISTINCT pr.child_fid) AS n_children
        FROM "{name}_02_pairs" pr
        JOIN "{name}_child_01" c ON c.fid = pr.child_fid
        WHERE pr.shared_area > 0
        GROUP BY c.source_file, pr.parent_fid
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_file_winner" AS
        SELECT source_file, parent_fid FROM (
            SELECT source_file, parent_fid,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_file ORDER BY n_children DESC, parent_fid ASC
                   ) AS rn
            FROM "{name}_02_file_votes"
        ) WHERE rn = 1
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_assign" AS
        SELECT c.fid AS child_fid, w.parent_fid
        FROM "{name}_child_01" c
        JOIN "{name}_02_file_winner" w ON w.source_file = c.source_file
        JOIN "{name}_02_pairs" pr
          ON pr.child_fid = c.fid
         AND pr.parent_fid = w.parent_fid
         AND pr.shared_area > 0
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02_unassigned" AS
        SELECT fid AS child_fid, source_file, geom
        FROM "{name}_child_01"
        WHERE fid NOT IN (SELECT child_fid FROM "{name}_02_assign")
    """)

    unassigned = conn.execute(f"""--sql
        SELECT child_fid FROM "{name}_02_unassigned" ORDER BY child_fid
    """).fetchall()
    if unassigned:
        fids = [row[0] for row in unassigned]
        logger.warning(
            "assign-one: dropping %d child fid(s) not in their file's "
            "assigned parent: %s",
            len(fids),
            fids,
        )

    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_file_votes"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_file_winner"')

    used_fids = [
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT parent_fid FROM "{name}_02_assign"'
        ).fetchall()
    ]
    where = (
        f"WHERE fid IN ({','.join(str(f) for f in used_fids)})"
        if used_fids
        else "WHERE FALSE"
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_parent_01" AS
        SELECT * FROM "{name}_parent_01" {where}
    """)
