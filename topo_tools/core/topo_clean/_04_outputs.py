"""Validates the cleaned output and exports the cleaned dataset + issues report."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_invalid_edges
from topo_tools.core.io import export_geometry_table, export_issues_table
from topo_tools.core.units import m2_per_deg2_factor

logger = getLogger(__name__)


def _add_outcome_columns(conn: DuckDBPyConnection, name: str) -> None:
    """Extend `{name}_02` with what actually happened to each issue during the fix.

    `fixed` is TRUE for every overlap row unconditionally, since `{name}_03`
    is already gated overlap-free; a gap row uses point-in-union containment.
    """
    m2_per_deg2 = m2_per_deg2_factor(conn, f"{name}_01")
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{name}_02" AS
        WITH before AS (SELECT fid, ST_Area(geom) AS area FROM "{name}_01"),
             after AS (SELECT fid, ST_Area(geom) AS area FROM "{name}_03"),
             fixed_union AS (SELECT ST_Union_Agg(geom) AS g FROM "{name}_03")
        SELECT
            i.key, i.kind, i.area_m2, i.max_width_m, i.thinness_ratio,
            i.unit_a, i.unit_b,
            (after_a.area - before_a.area) * {m2_per_deg2} AS unit_a_area_change_m2,
            (after_b.area - before_b.area) * {m2_per_deg2} AS unit_b_area_change_m2,
            CASE WHEN i.kind = 'gap'
                 THEN ST_Area(ST_Intersection(i.geom, fixed_union.g)) * {m2_per_deg2}
            END AS filled_area_m2,
            CASE WHEN i.kind = 'gap'
                 THEN ST_Contains(fixed_union.g, ST_PointOnSurface(i.geom))
                 ELSE TRUE
            END AS fixed,
            NULL::BIGINT AS parent_fid, NULL::VARCHAR AS reason,
            NULL::VARCHAR AS source_file,
            i.geom
        FROM "{name}_02" i
        LEFT JOIN before before_a ON before_a.fid = i.unit_a
        LEFT JOIN after after_a ON after_a.fid = i.unit_a
        LEFT JOIN before before_b ON before_b.fid = i.unit_b
        LEFT JOIN after after_b ON after_b.fid = i.unit_b
        CROSS JOIN fixed_union
    """)


def _warn_on_unfilled_gaps(conn: DuckDBPyConnection, name: str) -> None:
    """Log (never raise) the count of gaps `{name}_02.fixed` marks as still unfilled."""
    row = conn.execute(f"""--sql
        SELECT COUNT(*) FILTER (WHERE NOT fixed), COUNT(*)
        FROM "{name}_02" WHERE kind = 'gap'
    """).fetchall()[0]
    remaining, total = row
    if remaining:
        logger.warning(
            "clean: %d of %d detected gap(s) remain unfilled, see the issues file",
            remaining,
            total,
        )


def main(
    conn: DuckDBPyConnection,
    name: str,
    dest: Path,
    issues_dest: Path,
    *,
    debug: bool = False,
) -> None:
    """Validate `{name}_03` and export the cleaned dataset + issues report."""
    check_invalid_edges(conn, f"{name}_03")
    _add_outcome_columns(conn, name)
    _warn_on_unfilled_gaps(conn, name)

    export_geometry_table(conn, f"{name}_03", dest)
    export_issues_table(conn, f"{name}_02", issues_dest)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
