"""Assigns each (already-extended) child to the parent it shares the most area with."""

from logging import getLogger

from duckdb import DuckDBPyConnection

from topo_tools.core.match import _02_assign as match_assign

logger = getLogger(__name__)


def main(conn: DuckDBPyConnection, name: str) -> None:
    """Force every child in a source_file onto that file's single majority-vote parent.

    A file's children are one group (e.g. one country's admin2 units), not
    independently routed: this runs match's per-child plurality first (for
    its pairs table), then reassigns each whole file to whichever parent
    the most of its children intersect. A child that doesn't itself overlap
    its file's winning parent is reported unassigned, not force-clipped to
    an empty result. See docs/explanation/mosaic.md.
    """
    match_assign.main(conn, name)

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
            "mosaic: dropping %d child fid(s) not in their file's assigned parent: %s",
            len(fids),
            fids,
        )

    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_file_votes"')
    conn.execute(f'DROP TABLE IF EXISTS "{name}_02_file_winner"')
