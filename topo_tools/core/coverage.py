"""Shared coverage-topology validation and repair helpers."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.constants import (
    SNAP_ESCALATION_MAX_STEPS,
    SNAP_ESCALATION_STEP,
    SNAP_TOLERANCE,
)
from topo_tools.core.units import METERS_PER_DEGREE, m2_per_deg2_factor

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

    Dumps the union into parts first: ST_NumInteriorRings returns NULL on a
    MultiPolygon, and ST_Difference needs one polygon's own exterior ring.
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


def gap_issues_sql(
    conn: DuckDBPyConnection, table: str, *, min_width: float = SNAP_TOLERANCE
) -> str:
    """Build SQL for `table.geom`'s gap-kind issue rows, in the shared issues schema.

    Standalone or as one arm of a `UNION ALL BY NAME` with other issue kinds.
    """
    m2_per_deg2 = m2_per_deg2_factor(conn, table)
    width_m = f"(ST_MaximumInscribedCircle(geom)).radius * 2 * {METERS_PER_DEGREE}"
    thinness_ratio = "4 * pi() * ST_Area(geom) / POWER(ST_Perimeter(geom), 2)"
    return f"""
        SELECT 'gap-' || row_number() OVER () AS key, 'gap' AS kind,
               NULL::BIGINT AS unit_a, NULL::BIGINT AS unit_b,
               NULL::BIGINT AS parent_fid, NULL::VARCHAR AS reason,
               ST_Area(geom) * {m2_per_deg2} AS area_m2, {width_m} AS max_width_m,
               {thinness_ratio} AS thinness_ratio,
               NULL::DOUBLE AS unit_a_area_change_m2,
               NULL::DOUBLE AS unit_b_area_change_m2,
               NULL::DOUBLE AS filled_area_m2, FALSE AS fixed,
               NULL::VARCHAR AS source_file, geom
        FROM {gap_geometries_sql(table)}
        WHERE (ST_MaximumInscribedCircle(geom)).radius * 2 > {min_width}
    """


def short_source_file_sql(column: str) -> str:
    """Build SQL shortening a full source path to its last two path parts."""
    backslash = chr(92)
    posix_column = f"replace({column}, '{backslash}', '/')"
    return f"array_to_string(list_slice(str_split({posix_column}, '/'), -2, -1), '/')"


def assign_issue_rows_sql(name: str, *, source_file_expr: str = "NULL::VARCHAR") -> str:
    """Build SQL for `{name}_02_assign`'s code-join issue rows, in the shared schema.

    Requires `assignment_method`/`spatial_agrees` (assign_one/assign_many
    called with match columns); `source_file_expr` needs a real column or NULL.
    """
    return f"""
        SELECT 'code-mismatch-' || a.child_fid AS key, 'code-mismatch' AS kind,
               a.child_fid AS unit_a, NULL::BIGINT AS unit_b, a.parent_fid,
               'code join picked a different parent than spatial majority' AS reason,
               NULL::DOUBLE AS area_m2, NULL::DOUBLE AS max_width_m,
               NULL::DOUBLE AS thinness_ratio,
               NULL::DOUBLE AS unit_a_area_change_m2,
               NULL::DOUBLE AS unit_b_area_change_m2,
               NULL::DOUBLE AS filled_area_m2, FALSE AS fixed,
               {source_file_expr} AS source_file, c.geom
        FROM "{name}_02_assign" a
        JOIN "{name}_child_01" c ON c.fid = a.child_fid
        WHERE a.assignment_method = 'code' AND a.spatial_agrees IS NOT TRUE
        UNION ALL BY NAME
        SELECT 'code-fallback-' || a.child_fid AS key, 'code-fallback' AS kind,
               a.child_fid AS unit_a, NULL::BIGINT AS unit_b, a.parent_fid,
               'no matching code; fell back to spatial majority' AS reason,
               NULL::DOUBLE AS area_m2, NULL::DOUBLE AS max_width_m,
               NULL::DOUBLE AS thinness_ratio,
               NULL::DOUBLE AS unit_a_area_change_m2,
               NULL::DOUBLE AS unit_b_area_change_m2,
               NULL::DOUBLE AS filled_area_m2, FALSE AS fixed,
               {source_file_expr} AS source_file, c.geom
        FROM "{name}_02_assign" a
        JOIN "{name}_child_01" c ON c.fid = a.child_fid
        WHERE a.assignment_method = 'spatial_fallback'
    """


def has_gaps(
    conn: DuckDBPyConnection, table: str, *, gap_maximum_width: float = SNAP_TOLERANCE
) -> bool:
    """Return True if `table.geom` has an interior hole at or below gap_maximum_width.

    A wider hole may be a real geographic absence, not a defect;
    gap_maximum_width=0 tolerates no hole of any size.
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


def coverage_clean_escalating(
    conn: DuckDBPyConnection,
    table_in: str,
    table_out: str,
    *,
    fids: list[int] | None,
    gap_maximum_width: float | None = SNAP_TOLERANCE,
) -> None:
    """Coverage-clean, widening snapping_distance only as far as needed."""
    snap = SNAP_TOLERANCE
    for step in range(SNAP_ESCALATION_MAX_STEPS + 1):
        coverage_clean(
            conn,
            table_in,
            table_out,
            fids=fids,
            gap_maximum_width=gap_maximum_width,
            snapping_distance=snap,
        )
        if not has_invalid_edges(conn, table_out):
            if step:
                logger.info(
                    "coverage-clean: resolved invalid edges by escalating "
                    "snapping_distance to %s (step %d) on %s",
                    snap,
                    step,
                    table_out,
                )
            return
        snap += SNAP_ESCALATION_STEP
