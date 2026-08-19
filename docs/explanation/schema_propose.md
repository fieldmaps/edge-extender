# Schema Propose Explanation

`schema-propose` reads a source file's columns and a user-supplied
target-schema config, and proposes a source-column -> canonical-column
crosswalk, without touching the file. It replaces what `hdx-cod-ab-ai`
previously did by having a live Claude Code session freehand DuckDB
`DESCRIBE` queries and its own judgment: matching here is exact/alias/
regex-pattern/cardinality logic only, with no LLM call anywhere, so it's
reusable outside an agentic session and the matching decisions are
inspectable, versionable, and reproducible. `hdx-cod-ab-ai`'s PRD requires
that no stage ever auto-applies without a human confirming it first (see
its "no auto-approve mode" requirement); `schema-propose` never renames
anything itself, it only writes a crosswalk for a human to review, edit,
and hand to `schema-apply` (`docs/explanation/schema_apply.md`).

## Usage

```sh
topo-tools schema-propose example.geojson target-schema.yaml
```

```python
from topo_tools.api.schema_propose import schema_propose

schema_propose("example.parquet", "target-schema.yaml", "crosswalk.json")
```

`OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_crosswalk.json` name.

Run `topo-tools schema-propose --help` for the full, always-current option
list.

## Target-schema config

The target schema is config, not hardcoded, so `schema-propose` works on
any dataset, not just COD-AB (see `docs/examples/target-schemas/cod-ab.yaml`
for a working example). Each field has a `name`, optional `aliases`
(exact-match alternates), optional regex `patterns`, and optionally
`repeatable: {min, max}` for a field family that recurs once per admin
level (`adm{n}_name`, `adm{n}_pcode`). A config MAY declare a repeatable
catch-all alongside specific per-level fields (e.g. `adm1_name` with
`aliases: ["provincia"]`) when a country-specific alias is already known;
an exact/alias hit on the specific field always wins over the generic
catch-all's cardinality-based inference, since it needs no data read at
all.

## Pipeline

1. **`_01_inputs`**: reads and reprojects to EPSG:4326 via the shared
   `core.io.read_and_reproject()` helper, loading the full table rather
   than only its schema: the nesting inference below needs real distinct
   counts and containment checks, not just column names/types.
2. **`_02_propose`**: matches every source column against the target
   schema in four passes (below), writing one crosswalk row per column
   (`{name}_02`).
3. **`_03_outputs`**: exports `{name}_02` as the crosswalk JSON file. No
   hard gate: like `detect`, this tool never modifies geometry, so there's
   nothing to validate against.

## Matching passes

1. **Exact**: a source column's normalized (case/whitespace/punctuation-
   insensitive) name equals a field's own name or alias, or a repeatable
   field's name rendered at a specific level (e.g. `adm2_pcode`). Level is
   known immediately from the literal string; confidence `exact`.
2. **Role, then nesting inference**: a source column matching a repeatable
   field's alias or pattern, but not any specific rendered level, is a
   *role* match with the level unknown. Every such column, for the same
   field, is grouped into one candidate set and resolved together, see
   "Nesting-based level inference" below.
3. **Pattern**: a source column matching a non-repeatable field's regex
   pattern, not caught by pass 1, confidence `pattern`.
4. **Unmatched**: anything left over. `target_column` defaults to the
   column's own original name (retained, not dropped), confidence
   `unmatched`, so nothing silently disappears pending review.

## Nesting-based level inference

Real source files often carry a unit's own name/pcode alongside its
ancestors' as sibling columns (a district-level file that also has
`Nome_Prov`/`Nome_Mun` columns for its province and municipality). Which
admin level each belongs to isn't recoverable from the column name alone,
but it is recoverable from the data: a hierarchy nests, so a coarser
level's column has strictly fewer distinct values than a finer one, and
every value of the finer column maps to exactly one value of the coarser
one.

For a candidate set of two or more columns, `_order_and_validate()`
(`core/schema_propose/_02_propose.py`) orders by `COUNT(DISTINCT column)`
ascending, then checks every adjacent pair with `GROUP BY finer HAVING
COUNT(DISTINCT coarser) > 1`: any row returned means some finer-column
value spans more than one coarser-column value, i.e. not a real
containment relationship, just coincidentally similar cardinality. A tie
in distinct counts, or any failed containment check, marks the **whole**
candidate set `ambiguous` rather than resolving part of it: splitting the
chain at the failure point and auto-resolving the rest risks silently
mis-assigning a level in published administrative boundary data, so the
whole set defers to a human instead.

This only establishes *relative* order (coarsest to finest), never an
absolute admin-level number, deliberately: real source files often skip
levels (a file with only `adm1`/`adm3`/`adm4` columns, no `adm2`), so
decrementing from a known point would silently mislabel the gap. `--own-
level N` anchors only the **finest** column in a validated chain (the
file's own level, closest to its row count) to a concrete number,
confidence `exact`; every coarser column in the chain is left
`nesting-validated-relative`, retained under its own original name (same
"nothing silently disappears" rule as the `unmatched` pass), its crosswalk
`note` naming its rank and the column it's coarser than, for a human to
assign the real number. Without `--own-level`, even the finest column
stays a relative placeholder. `--own-level` itself is bounds-checked
against the matched field's declared `repeatable` range, raising
`ValueError` if it falls outside it.

Name-role and pcode-role columns are matched as fully independent
candidate sets (one per target field), never cross-referenced: a level
missing one role entirely (an embedded ancestor pcode with no matching
name column, or vice versa, both common in real source files) simply
yields no candidate for that field, nothing forced.

## Not modeled in v1

- `adm{n}_name1`/`name2`/`name3` (alternate-language names) aren't part of
  the shipped COD-AB example config: they don't vary by admin level the
  way `adm{n}_name`/`adm{n}_pcode` do, so the cardinality/nesting
  inference above doesn't help distinguish `name1` from `name2` from
  `name3`. Model them as your own non-repeatable fields once you know
  which source column holds which language.
- Reusing this matching logic from inside `match`/`mosaic`/`clean` isn't
  wired up; nothing currently needs it internally. If that changes, follow
  the precedent `docs/adr/0028` sets for `detect`: extract the shared
  logic into a leaf module first.
