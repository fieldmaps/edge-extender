"""Direct core.assign tests: code-join precedence, fallback, and default schema."""

import duckdb
import pytest

from topo_tools.core.assign import (
    assign_many,
    assign_one,
    child_bbox_extent,
    prepare_parent_tiles,
)

# Two disjoint parents, far enough apart that a child spans the empty gap
# between them without touching anything else.
_PARENT_WKT = [
    (1, "POLYGON((0 0, 3 0, 3 3, 0 3, 0 0))", "P1"),
    (2, "POLYGON((10 0, 13 0, 13 3, 10 3, 10 0))", "P2"),
]


def _connect_with_parents():
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    values = ", ".join(
        f"({fid}, ST_GeomFromText('{wkt}'), '{code}')" for fid, wkt, code in _PARENT_WKT
    )
    conn.execute(f"""--sql
        CREATE TABLE t_parent_01 AS
        SELECT * FROM (VALUES {values}) AS v(fid, geom, pcode)
    """)
    return conn


def test_assign_many_default_schema_unchanged():
    """No match columns: `_02_assign` stays exactly (child_fid, parent_fid)."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText(
                'POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'
            ), 'fileA')
        ) AS v(fid, geom, source_file)
    """)
    assign_many(conn, "t")
    cols = [d[0] for d in conn.execute('SELECT * FROM "t_02_assign"').description]
    assert cols == ["child_fid", "parent_fid"]


def test_assign_many_code_join_precedence_and_fallback():
    """Code wins on disagreement, falls back to spatial when unmatched/unrelated."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            -- agrees: entirely inside P1, code also says P1
            (1, ST_GeomFromText(
                'POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'
            ), 'P1'),
            -- mismatch: mostly overlaps P1 (area 2) but touches P2 too (area
            -- 0.5); code says P2, which it does overlap, so code wins anyway
            (2, ST_GeomFromText(
                'POLYGON((1 0, 10.5 0, 10.5 1, 1 1, 1 0))'
            ), 'P2'),
            -- fallback: no parent has this code at all
            (3, ST_GeomFromText(
                'POLYGON((1.5 1.5, 2 1.5, 2 2, 1.5 2, 1.5 1.5))'
            ), 'ZZZ'),
            -- fallback: code says P2, but this child doesn't overlap P2 at all
            (4, ST_GeomFromText(
                'POLYGON((1.5 0.2, 2 0.2, 2 0.6, 1.5 0.6, 1.5 0.2))'
            ), 'P2')
        ) AS v(fid, geom, pcode)
    """)
    conn.execute("""--sql
        ALTER TABLE t_child_01 ADD COLUMN source_file VARCHAR DEFAULT 'fileA'
    """)

    assign_many(conn, "t", parent_match_column="pcode", child_match_column="pcode")

    rows = {
        row[0]: row[1:]
        for row in conn.execute("""--sql
            SELECT child_fid, parent_fid, assignment_method, spatial_agrees
            FROM "t_02_assign" ORDER BY child_fid
        """).fetchall()
    }
    assert rows[1] == (1, "code", True)
    assert rows[2] == (2, "code", False)
    assert rows[3] == (1, "spatial_fallback", None)
    assert rows[4] == (1, "spatial_fallback", None)

    unassigned = conn.execute('SELECT COUNT(*) FROM "t_02_unassigned"').fetchone()[0]
    assert unassigned == 0


def test_assign_many_carry_columns_populates_parent_attributes():
    """carry_columns copies named parent columns onto every matched child row."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText(
                'POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'
            ), 'fileA')
        ) AS v(fid, geom, source_file)
    """)
    assign_many(conn, "t", carry_columns=["pcode"])
    row = conn.execute("""--sql
        SELECT child_fid, parent_fid, pcode FROM "t_02_assign"
    """).fetchone()
    assert row == (1, 1, "P1")


def test_child_bbox_extent_combines_child_rows():
    """Returns the combined (xmin, ymin, xmax, ymax) across every child row."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
            (2, ST_GeomFromText('POLYGON((5 5, 6 5, 6 6, 5 6, 5 5))'))
        ) AS v(fid, geom)
    """)
    assert child_bbox_extent(conn, "t") == (0.0, 0.0, 6.0, 6.0)


def test_child_bbox_extent_none_when_empty():
    """Returns None rather than a row of NULLs for a table with zero rows."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    conn.execute("CREATE TABLE t_child_01 (fid BIGINT, geom GEOMETRY)")
    assert child_bbox_extent(conn, "t") is None


def test_prepare_parent_tiles_child_bbox_filters_distant_parts():
    """A child_bbox drops parent parts whose bbox can't overlap it."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    conn.execute("""--sql
        CREATE TABLE t_parent_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
            (2, ST_GeomFromText(
                'POLYGON((100 100, 101 100, 101 101, 100 101, 100 100))'
            )),
            (3, ST_GeomFromText(
                'POLYGON((200 200, 201 200, 201 201, 200 201, 200 200))'
            ))
        ) AS v(fid, geom)
    """)

    prepare_parent_tiles(conn, "t", child_bbox=(0.0, 0.0, 1.0, 1.0))
    filtered_fids = {
        row[0] for row in conn.execute('SELECT fid FROM "t_02_parent_parts"').fetchall()
    }
    assert filtered_fids == {1}

    prepare_parent_tiles(conn, "t")
    all_fids = {
        row[0] for row in conn.execute('SELECT fid FROM "t_02_parent_parts"').fetchall()
    }
    assert all_fids == {1, 2, 3}


def test_assign_one_carry_columns_populates_parent_attributes():
    """carry_columns copies named parent columns onto every matched child row."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (10, ST_GeomFromText(
                'POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'
            ), 'fileA')
        ) AS v(fid, geom, source_file)
    """)
    assign_one(conn, "t", carry_columns=["pcode"])
    row = conn.execute("""--sql
        SELECT child_fid, parent_fid, pcode FROM "t_02_assign"
    """).fetchone()
    assert row == (10, 1, "P1")


def test_assign_carry_columns_collision_raises():
    """A carry_columns name reserved by `_02_assign` itself raises ValueError."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText('POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'))
        ) AS v(fid, geom)
    """)
    with pytest.raises(ValueError, match="reserved assign column"):
        assign_many(conn, "t", carry_columns=["parent_fid"])


def test_assign_carry_columns_child_schema_collision_raises():
    """A carry_columns name already present on the child layer raises ValueError."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            (1, ST_GeomFromText('POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))'), 'X')
        ) AS v(fid, geom, pcode)
    """)
    with pytest.raises(ValueError, match="child layer's own column"):
        assign_many(conn, "t", carry_columns=["pcode"])


def test_assign_one_code_join_precedence_and_fallback():
    """Same precedence/fallback rules, applied per source_file, one parent each."""
    conn = _connect_with_parents()
    conn.execute("""--sql
        CREATE TABLE t_child_01 AS SELECT * FROM (VALUES
            -- fileA: both children mostly overlap P1 but code agrees on P2,
            -- which they both also overlap, so the whole file moves to P2
            (10, ST_GeomFromText(
                'POLYGON((1 0, 10.5 0, 10.5 1, 1 1, 1 0))'
            ), 'P2', 'fileA'),
            (11, ST_GeomFromText(
                'POLYGON((1 1, 10.5 1, 10.5 2, 1 2, 1 1))'
            ), 'P2', 'fileA'),
            -- fileB: no code match at all, falls back to its spatial winner (P1)
            (20, ST_GeomFromText(
                'POLYGON((1.5 0.2, 2 0.2, 2 0.6, 1.5 0.6, 1.5 0.2))'
            ), 'ZZZZ', 'fileB')
        ) AS v(fid, geom, pcode, source_file)
    """)

    assign_one(conn, "t", parent_match_column="pcode", child_match_column="pcode")

    rows = {
        row[0]: row[1:]
        for row in conn.execute("""--sql
            SELECT child_fid, parent_fid, assignment_method, spatial_agrees
            FROM "t_02_assign" ORDER BY child_fid
        """).fetchall()
    }
    assert rows[10] == (2, "code", False)
    assert rows[11] == (2, "code", False)
    assert rows[20] == (1, "spatial_fallback", None)

    unassigned = conn.execute('SELECT COUNT(*) FROM "t_02_unassigned"').fetchone()[0]
    assert unassigned == 0
