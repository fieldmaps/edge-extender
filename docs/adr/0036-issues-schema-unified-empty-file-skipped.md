# 0036: issues report schema unified; empty file skipped

## Status

Accepted.

## Context

`clean`, `match`, and `mosaic` each had their own issues-table schema,
grown independently: `clean`'s carried `key`/`kind`/`area_m2`/
`max_width_m`/`thinness_ratio`/`unit_a`/`unit_b` plus its own fix-outcome
columns; `match`/`mosaic` carried `key`/`kind`/`child_fid`/`parent_fid`/
`reason`(/`source_file` for `mosaic`), no relation to `clean`'s column
names or types. `stitch` had no issues report at all until
`docs/adr/0035` gave it one for leftover gaps, which would have meant a
fourth, again-different schema.

All four tools' issues tables always wrote a file too, even with zero
rows, so a clean run left behind an empty-but-present issues file
indistinguishable at a glance from "not checked yet."

None of these tables have any downstream consumer inside or outside this
codebase; the fragmentation was pure historical accretion, not a
requirement.

## Decision

One column schema across `clean`/`match`/`mosaic`/`stitch`'s issues
tables: `key`, `kind`, `area_m2`, `max_width_m`, `thinness_ratio`,
`unit_a`, `unit_b`, `parent_fid`, `reason`, `unit_a_area_change_m2`,
`unit_b_area_change_m2`, `filled_area_m2`, `fixed`, `source_file`,
`geom`. `unit_a` takes over `child_fid`'s old role in `match`/`mosaic`,
consistent with its existing meaning in `clean`'s overlap rows ("a
primary fid involved"). Every kind leaves inapplicable columns null, the
same convention `clean`'s own table already used. Each tool's SQL builds
its own rows with `UNION ALL BY NAME` rather than positional `UNION ALL`,
so a column present in one row-kind's branch but not another still lines
up correctly without every branch having to spell out every column.

New shared `export_issues_table()` (`core/io.py`) replaces each tool's
direct `export_geometry_table()` call for its issues table: exports only
when the table has at least one row; when it would be empty, deletes any
stale file already at that destination from a previous run instead of
writing (or leaving behind) an empty one.

## Consequences

`clean`/`match`/`mosaic`'s previously-documented "MUST always produce the
issues report, even when empty" contract is reversed: absence of the file
now means "no issues," not "not run yet." Any caller scripting around the
old always-present guarantee must switch to checking for the file's
existence instead of opening it and finding zero rows.
`tests/test_clean.py`/`test_match.py`/`test_mosaic.py`'s empty-issues
tests were renamed and inverted to assert non-existence; column-list
assertions across all three (plus new `test_stitch.py` issues tests)
updated for the shared schema. See `docs/reference/shared.md`'s "Issues
report schema" section for the authoritative column list and `docs/adr/0035`
for the gap-tolerance change that gave `stitch` its first issues rows.
