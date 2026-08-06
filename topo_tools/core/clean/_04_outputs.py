"""Validates the cleaned output and exports the cleaned dataset + issues report."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import check_overlaps
from topo_tools.core.io import export_geometry_table

from ._02_issues import centroid_lat_of
from ._units import METERS_PER_DEGREE, cos_lat_factor

logger = getLogger(__name__)


def _add_outcome_columns(conn: DuckDBPyConnection, name: str) -> None:
    """Extend `{name}_02` with what actually happened to each issue during the fix.

    Detection rows only describe the defect as found; this adds the
    measured outcome -- each named unit's own real area change for an
    overlap row, how much of the gap's own area ended up covered for a gap
    row -- in the same square-meters units as `area_m2`.
    """
    m2_per_deg2 = METERS_PER_DEGREE**2 * cos_lat_factor(
        centroid_lat_of(conn, f"{name}_01")
    )
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
            i.geom
        FROM "{name}_02" i
        LEFT JOIN before before_a ON before_a.fid = i.unit_a
        LEFT JOIN after after_a ON after_a.fid = i.unit_a
        LEFT JOIN before before_b ON before_b.fid = i.unit_b
        LEFT JOIN after after_b ON after_b.fid = i.unit_b
        CROSS JOIN fixed_union
    """)


def _warn_on_unfilled_gaps(conn: DuckDBPyConnection, name: str) -> None:
    """Log (never raise) how many detected gaps remain uncovered by `{name}_03`.

    Unlike extend/match, clean can legitimately leave gaps unfilled by design
    (--gap-width auto, or a numeric cap narrower than some detected gap) --
    this is visibility for the issues file, not a failure condition.

    Checks for any gap rows first -- the whole-table union below is expensive
    (it's the same cost as issues' own gap-detection union) and DuckDB can't
    skip computing it just because the join against `_02` turns out empty.
    """
    has_gaps = conn.execute(f"""--sql
        SELECT EXISTS (SELECT 1 FROM "{name}_02" WHERE kind = 'gap')
    """).fetchall()[0][0]
    if not has_gaps:
        return

    row = conn.execute(f"""--sql
        WITH u AS (SELECT ST_Union_Agg(geom) AS g FROM "{name}_03")
        SELECT
            COUNT(*) FILTER (WHERE NOT ST_Contains(u.g, ST_PointOnSurface(i.geom))),
            COUNT(*)
        FROM "{name}_02" i, u
        WHERE i.kind = 'gap'
    """).fetchall()[0]
    remaining, total = row
    if remaining:
        logger.warning(
            "clean: %d of %d detected gap(s) remain unfilled -- see the issues file",
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
    check_overlaps(conn, f"{name}_03")
    _warn_on_unfilled_gaps(conn, name)
    _add_outcome_columns(conn, name)

    export_geometry_table(conn, f"{name}_03", dest)
    export_geometry_table(conn, f"{name}_02", issues_dest, exclude_fid=False)

    if not debug:
        conn.execute(f'DROP TABLE IF EXISTS "{name}_01"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_02"')
        conn.execute(f'DROP TABLE IF EXISTS "{name}_03"')
