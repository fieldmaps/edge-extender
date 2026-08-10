"""Shared coverage-topology validation and repair helpers."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import SNAP_TOLERANCE

logger = getLogger(__name__)


def has_invalid_edges(conn: DuckDBPyConnection, table: str) -> bool:
    """Return True if `table.geom` has any overlaps or unmatched shared edges."""
    return conn.execute(f"""--sql
        SELECT ST_CoverageInvalidEdges_Agg(geom, {SNAP_TOLERANCE}) IS NOT NULL
        FROM (SELECT UNNEST(ST_Dump(geom)).geom AS geom FROM "{table}")
    """).fetchall()[0][0]


def check_invalid_edges(conn: DuckDBPyConnection, table: str) -> None:
    """Raise RuntimeError if `table.geom` has any overlaps or unmatched shared edges."""
    if has_invalid_edges(conn, table):
        error = f"INVALID_EDGES: {table}"
        logger.error(error)
        raise RuntimeError(error)


def gap_geometries_sql(table: str) -> str:
    """Build SQL for a subquery of individual fully-enclosed interior-hole geometries.

    Dumps the union into parts first: ST_NumInteriorRings silently returns
    NULL on a MultiPolygon, and ST_Difference needs one polygon's own
    exterior ring, not the whole union's.
    """
    return f"""(
        WITH u AS (
            SELECT ST_Union_Agg(geom) AS g
            FROM (SELECT UNNEST(ST_Dump(geom)).geom AS geom FROM "{table}")
        ),
        parts AS (
            SELECT (UNNEST(ST_Dump(g))).geom AS poly FROM u WHERE g IS NOT NULL
        ),
        holes AS (
            SELECT UNNEST(ST_Dump(
                ST_Difference(ST_MakePolygon(ST_ExteriorRing(poly)), poly)
            )).geom AS geom
            FROM parts WHERE ST_NumInteriorRings(poly) > 0
        )
        SELECT geom FROM holes WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
    )"""


def has_gaps(
    conn: DuckDBPyConnection, table: str, *, gap_maximum_width: float = SNAP_TOLERANCE
) -> bool:
    """Return True if `table.geom` has an interior hole at or below gap_maximum_width.

    A wider hole may be a real geographic absence (e.g. one country fully
    enclosing another), not a coverage defect. gap_maximum_width=0
    tolerates no hole of any size.
    """
    if gap_maximum_width == 0:
        max_interior_rings = conn.execute(f"""--sql
            WITH u AS (
                SELECT ST_Union_Agg(geom) AS g
                FROM (SELECT UNNEST(ST_Dump(geom)).geom AS geom FROM "{table}")
            )
            SELECT MAX(ST_NumInteriorRings(part))
            FROM (SELECT UNNEST(ST_Dump(g)).geom AS part FROM u)
        """).fetchall()[0][0]
        return (max_interior_rings or 0) > 0

    return conn.execute(f"""--sql
        SELECT EXISTS (
            SELECT 1 FROM {gap_geometries_sql(table)} h
            WHERE (ST_MaximumInscribedCircle(h.geom)).radius * 2 <= {gap_maximum_width}
        )
    """).fetchall()[0][0]


def check_gaps(
    conn: DuckDBPyConnection, table: str, *, gap_maximum_width: float = SNAP_TOLERANCE
) -> None:
    """Raise RuntimeError if `table.geom`'s union has a qualifying interior hole."""
    if has_gaps(conn, table, gap_maximum_width=gap_maximum_width):
        error = f"GAPS: {table}"
        logger.error(error)
        raise RuntimeError(error)


def count_gaps(conn: DuckDBPyConnection, table: str, *, min_width: float = 0) -> int:
    """Count interior holes in `table.geom`'s union that are wider than min_width."""
    return conn.execute(f"""--sql
        SELECT COUNT(*) FROM {gap_geometries_sql(table)} h
        WHERE (ST_MaximumInscribedCircle(h.geom)).radius * 2 > {min_width}
    """).fetchall()[0][0]


def has_valid_topology(
    conn: DuckDBPyConnection, table: str, *, gap_maximum_width: float = SNAP_TOLERANCE
) -> bool:
    """Return True if `table.geom` has no overlaps, unmatched shared edges, or gaps."""
    return not has_invalid_edges(conn, table) and not has_gaps(
        conn, table, gap_maximum_width=gap_maximum_width
    )


def check_valid_topology(
    conn: DuckDBPyConnection, table: str, *, gap_maximum_width: float = SNAP_TOLERANCE
) -> None:
    """Raise RuntimeError if `table.geom` has any overlaps, edge mismatch, or gaps."""
    check_invalid_edges(conn, table)
    check_gaps(conn, table, gap_maximum_width=gap_maximum_width)


def coverage_clean(  # noqa: PLR0913 (each param is a distinct required input, not decomposable)
    conn: DuckDBPyConnection,
    table_in: str,
    table_out: str,
    *,
    fids: list[int] | None,
    gap_maximum_width: float | None = SNAP_TOLERANCE,
    snapping_distance: float | None = SNAP_TOLERANCE,
) -> None:
    """Write table_out from table_in with ST_CoverageClean applied to a subset (or all).

    ST_CoverageClean returns a GeometryCollection whose i-th element
    corresponds to input i, so rows are mapped back via ST_Dump's path[1].
    """
    where = "" if fids is None else f"WHERE fid IN ({','.join(str(f) for f in fids)})"
    snap_arg = -1 if snapping_distance is None else snapping_distance
    gap_arg = -1 if gap_maximum_width is None else gap_maximum_width
    cc = f"ST_CoverageClean(list(geom ORDER BY fid), {snap_arg}, {gap_arg})"
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{table_out}" AS
        WITH ord AS (
            SELECT fid, row_number() OVER (ORDER BY fid) AS rn
            FROM "{table_in}" {where}
        ),
        coll AS (
            SELECT {cc} AS g FROM "{table_in}" {where}
        ),
        dumped AS (
            SELECT (d).path[1] AS rn, (d).geom AS sub
            FROM (SELECT UNNEST(ST_Dump(g)) AS d FROM coll)
        ),
        grouped AS (
            SELECT rn, list(sub) AS subs FROM dumped GROUP BY rn
        ),
        parts AS (
            SELECT rn,
                   CASE WHEN len(subs) = 1 THEN subs[1] ELSE ST_Collect(subs) END
                       AS cleaned_geom
            FROM grouped
        ),
        mapping AS (
            SELECT ord.fid, parts.cleaned_geom
            FROM ord JOIN parts USING (rn)
        )
        SELECT t.* EXCLUDE (geom),
               COALESCE(m.cleaned_geom, t.geom) AS geom
        FROM "{table_in}" t
        LEFT JOIN mapping m USING (fid)
    """)
