"""Resolves an include/exclude column filter pair against a table's real schema."""

from duckdb import DuckDBPyConnection


def resolve_column_selection(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    table: str,
    *,
    include: list[str] | None,
    exclude: list[str] | None,
    always_exclude: tuple[str, ...] = (),
    always_include: tuple[str, ...] = (),
) -> list[str]:
    """Resolve include/exclude against `table`'s schema into a concrete list."""
    if include and exclude:
        msg = "include and exclude are mutually exclusive"
        raise ValueError(msg)
    if exclude:
        collisions = set(exclude) & set(always_include)
        if collisions:
            msg = (
                f"exclude collides with always-included column(s): {sorted(collisions)}"
            )
            raise ValueError(msg)

    columns = [row[0] for row in conn.execute(f'DESCRIBE "{table}"').fetchall()]

    if include:
        selected = list(include)
        for col in always_include:
            if col not in selected:
                selected.append(col)
    elif exclude:
        exclude_set = set(exclude)
        selected = [c for c in columns if c not in exclude_set]
    else:
        selected = list(columns)

    always_exclude_set = set(always_exclude)
    return [c for c in selected if c not in always_exclude_set]


def validate_merge_flags(  # noqa: PLR0913
    *,
    merge: bool,
    parent_include: list[str] | None,
    parent_exclude: list[str] | None,
    child_include: list[str] | None,
    child_exclude: list[str] | None,
    prefer: str | None,
) -> None:
    """Raise on mutual-exclusion/require-merge violations among the merge flags."""
    if parent_include and parent_exclude:
        msg = "parent_include and parent_exclude are mutually exclusive"
        raise ValueError(msg)
    if child_include and child_exclude:
        msg = "child_include and child_exclude are mutually exclusive"
        raise ValueError(msg)
    if prefer is not None and prefer not in ("parent", "child"):
        msg = "prefer must be 'parent' or 'child'"
        raise ValueError(msg)
    narrowing_given = bool(
        parent_include or parent_exclude or child_include or child_exclude
    )
    if prefer and narrowing_given:
        msg = (
            "prefer is mutually exclusive with "
            "parent_include/parent_exclude/child_include/child_exclude"
        )
        raise ValueError(msg)
    if not merge and (narrowing_given or prefer):
        msg = (
            "parent_include/parent_exclude/child_include/child_exclude/prefer "
            "require merge=True"
        )
        raise ValueError(msg)


def resolve_merge_columns(  # noqa: PLR0913
    conn: DuckDBPyConnection,
    name: str,
    *,
    merge: bool,
    parent_include: list[str] | None,
    parent_exclude: list[str] | None,
    child_include: list[str] | None,
    child_exclude: list[str] | None,
    prefer: str | None,
) -> tuple[list[str] | None, list[str] | None]:
    """Resolve merge settings into concrete (parent_columns, child_columns) lists."""
    if not merge:
        return None, None
    parent_columns = resolve_column_selection(
        conn,
        f"{name}_parent_01",
        include=parent_include,
        exclude=parent_exclude,
        always_exclude=("fid", "geom"),
    )
    child_columns = resolve_column_selection(
        conn,
        f"{name}_child_01",
        include=child_include,
        exclude=child_exclude,
        always_include=("fid", "geom", "source_file"),
    )
    if prefer == "parent":
        child_columns = [c for c in child_columns if c not in set(parent_columns)]
    elif prefer == "child":
        parent_columns = [c for c in parent_columns if c not in set(child_columns)]
    return parent_columns, child_columns
