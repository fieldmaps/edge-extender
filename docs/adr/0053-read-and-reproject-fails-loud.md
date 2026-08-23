# 0053: `read_and_reproject()` fails loud on unreadable geometry or a 0-row read

## Status

Accepted.

## Context

Broad testing of `map`/`crosswalk` against real government FileGDBs and
shapefiles in `hdx-cod-ab-ai` surfaced two silent-failure modes in
`core.io.read_and_reproject()`, the shared read stage every tool calls:

- A malformed shapefile ring (`syr/raw/ver1/Governate00.shp`) made
  `ST_MakeValid` raise a raw `duckdb.InvalidInputException`
  ("IllegalArgumentException: Points of LinearRing do not form a closed
  linestring"), an unhandled exception/traceback rather than the clean
  `ValueError` this codebase uses for every other known-bad-input case.
- Two real Mozambique FileGDBs, confirmed by a system-installed GDAL
  (3.13.3) to have full schemas and hundreds of features each, read back
  as effectively empty (zero attribute columns beyond `OGC_FID`/`geom`,
  zero rows) through DuckDB spatial's own bundled/vendored GDAL build.
  `map`/`crosswalk` didn't crash; they silently "succeeded" with a
  crosswalk of 100% gap rows, on what should have been the easiest,
  already-COD-AB-formatted test case. Re-exporting the same layer via
  `gdal vector convert` to GeoParquet before feeding it to `map` read
  correctly, confirming the gap is specific to DuckDB spatial's bundled
  GDAL version/build, not a flaw in the source file or in `map`'s own
  matching logic.

## Decision

`read_and_reproject()` now fails loud in both cases instead of silently
propagating a raw exception or a garbage empty result:

- The `CREATE TABLE ... AS SELECT` that reads and reprojects is wrapped
  in a `try`/`except duckdb.Error`, re-raised as `ValueError` naming the
  likely cause (invalid geometry `ST_MakeValid` can't repair).
- After the table is built, a zero-row result raises `ValueError`
  immediately, naming DuckDB spatial's bundled GDAL as the likely cause
  and suggesting the actual working fix (re-export via `gdal vector
  convert` to GeoParquet/GPKG first, then feed that to the tool).

Both checks live in the one shared leaf function every tool already
calls, so the fix applies uniformly without touching any tool's own
code.

## Consequences

A source file this codebase genuinely cannot read (broken geometry, or a
FileGDB variant DuckDB spatial's bundled GDAL can't parse) now raises
immediately with an actionable message, instead of a tool completing
"successfully" against data it never actually read. The zero-row check
assumes no legitimate caller ever hands any tool a deliberately empty
geodata file; every tool in this codebase requires real features to do
its own job, so this is a safe assumption, not a behavior change for any
real workflow.
