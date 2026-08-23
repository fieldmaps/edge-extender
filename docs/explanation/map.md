# Map Explanation

`map` reads a source file's columns and a target-schema config (a bundled
default, or user-supplied), and maps a source-column -> canonical-column
crosswalk, without touching the file. It replaces what `hdx-cod-ab-ai`
previously did by having a live Claude Code session freehand DuckDB
`DESCRIBE` queries and its own judgment: matching here is value-shape and
cardinality/containment logic only, with no LLM call and no column-name
vocabulary anywhere, so it's reusable outside an agentic session and the
matching decisions are inspectable, versionable, and reproducible.
`hdx-cod-ab-ai`'s PRD requires that no stage ever auto-applies without a
human confirming it first (see its "no auto-approve mode" requirement);
`map` never renames anything itself, it only writes a crosswalk for a
human to review, edit, and hand to `refactor`
(`docs/explanation/refactor.md`).

## Why column names are never a matching signal

Real source files never reliably use a target schema's vocabulary: a
GRID3 health-zone layer uses French field names, a national mapping
agency's shapefile uses its own local convention, and no alias/pattern
list can anticipate every source vocabulary in advance. Treating column
names as signal is unreliable by construction, not just under-tuned. What
every admin boundary file *does* share, regardless of vocabulary, is
structure: a hierarchy nests (each finer unit belongs to exactly one
coarser unit), and within a level, a code column and a name column look
different from each other in their raw values. `map` uses only those two
structural facts. See `docs/adr/0054` for the empirical evidence (a real
Madagascar admin4 shapefile) that motivated replacing the earlier
name/alias/pattern-based design with this one.

## Usage

```sh
topo-tools map example.geojson
```

```python
from topo_tools.api.map import map

map("example.parquet")
```

`TARGET_SCHEMA_FILE` (positional, optional) defaults to the bundled COD-AB
schema. `OUTPUT_FILE` (positional, optional) defaults to `INPUT_FILE` with a
`_crosswalk.csv` name.

Run `topo-tools map --help` for the full, always-current option
list.

## Target-schema config

The target schema is config, not hardcoded, so `map` works on any
dataset, not just COD-AB; omit `TARGET_SCHEMA_FILE` to use the bundled
default (`topo_tools/core/map/data/cod-ab.yaml`), or pass your own. A
config is just two naming templates, `name_field` and `code_field` (e.g.
`"adm{n}_name"`/`"adm{n}_pcode"`), each containing a `{n}` placeholder for
the discovered admin level. They control output naming only; `map` never
reads them while deciding what belongs to which level.

## Pipeline

1. **`_01_inputs`**: reads and reprojects to EPSG:4326 via the shared
   `core.io.read_and_reproject()` helper, loading the full table rather
   than only its schema: the structural inference below needs real
   distinct counts, value shapes, and containment checks, not just
   column names/types.
2. **`_02_map`**: excludes GIS bookkeeping noise columns
   (`core.constants.NOISE_COLUMNS`), shape-classifies and structurally
   positions every remaining source column (below), reorders everything,
   and writes one crosswalk row per column (`{name}_02`).
3. **`_03_outputs`**: exports `{name}_02` as the crosswalk CSV file. No
   hard gate: like `detect`, this tool never modifies geometry, so there's
   nothing to validate against.

## Algorithm

1. **Shape-classify every candidate column** by its own values: a
   majority-vote SQL predicate checks what fraction of each column's
   non-null values match COD-AB's own documented p-code format
   (`^[A-Za-z]{1,4}[0-9]+$`, letter prefix plus digit suffix). At or above
   75% match, the column is `code`-shaped; at or below 10%, `name`-shaped;
   otherwise `ambiguous`. A constant (distinct count 1) column whose sole
   value is bare uppercase letters (`^[A-Z]{1,4}$`) is reclassified
   `code`-shaped too, recovering COD-AB's admin0 pcode convention (a bare
   ISO2/3 country code, no digit suffix, e.g. `"MG"`), which otherwise
   fails the letter-plus-digit regex (see `docs/adr/0055`).
2. **Build the code-only hierarchy chain** (`_build_code_groups()` +
   `_chain_from_groups()`, `core/map/_02_map.py`): group code-shaped
   columns by identical `COUNT(DISTINCT)` (constants, distinct count 1,
   are kept, not dropped: a single-country file's admin0 code is
   legitimately constant), verify a same-count group is truly bijective
   in both directions before treating its columns as same-level
   companions (a group that fails is demoted to singleton columns, each
   still eligible to chain on its own), then walk the groups
   coarsest-to-finest joining adjacent pairs only when
   `GROUP BY finer HAVING COUNT(DISTINCT coarser) > 1` returns zero rows.
   A failed join splits the run into independent chains. The **longest**
   resulting chain is treated as the discovered admin hierarchy; each
   adjacent link is also checked for the fraction of rows where the finer
   code's value literally starts with the coarser code's value (COD-AB's
   own p-code nesting convention), a corroborating signal surfaced in the
   row's `note` only when it's below 100%, not a hard requirement, since
   real data can have documented exceptions to it.
3. **Bracket every non-code column into the chain by cardinality**
   (`_bracket_other_columns()`): a name-shaped or shape-ambiguous column
   lands at chain level `k` if `code_count[k-1] < COUNT(DISTINCT col) <=
   code_count[k]` (`code_count[-1]` is 0). A column whose count doesn't
   fall into exactly one bracket is left unmatched. Landing in a bracket
   wins the `name` tier for every bracketed column there that also passes
   a same-level function check against that level's code column
   (`GROUP BY code HAVING COUNT(DISTINCT candidate) > 1` returns zero
   rows, i.e. every code value maps to exactly one value of the
   candidate): real name columns fail a direct containment check against
   a *different* level's code (the same name legitimately repeats under
   different parents), but must pass it against their *own* level's
   code, since a given unit's code always has exactly one name. A
   candidate that's also **bijective** with the level's code (an exact
   count-and-value match, not just a repeats-tolerant function) wins over
   a looser match: when at least one exact match exists at a level, only
   exact matches resolve, and every other function-passing candidate
   there stays `ambiguous`, naming the exact match (see `docs/adr/0057`).
   A bracketed column that fails the function check entirely also stays
   `ambiguous`.
4. **Number and assign levels, emit rows**: a chain position's level
   number is always its relative rank (0 = coarsest). `map` never takes a
   real admin number as input, it only infers nesting depth (see
   `docs/adr/0058`). Every code-chain column and every winning bracketed
   name column becomes a `code`/`name` row, `target_column` always
   rendered from the schema template at that level; when two or more
   qualify at the same level (bijective code companions, or multiple
   exact-or-functional name matches), each is numbered by source-column
   order, the first getting the bare template (`adm2_name`, `adm2_pcode`)
   and each next one the template plus an appended integer
   (`adm2_name1`, `adm2_pcode1`, ...) (see `docs/adr/0056`). **Admin
   level 0 is never resolved** (code or name): both this step and step 3
   skip any chain position whose resolved level is `0` (see
   `docs/adr/0057`). Everything else becomes `ambiguous` (bracketed but
   shape-ambiguous, failing the function check, or losing to an exact
   match; or code-shaped but outside the chain) or `unmatched`,
   `target_column` left empty in either case: `refactor` drops a column
   whose crosswalk `target_column` is empty, so keeping one under its own
   name is a decision a human makes by editing the crosswalk, not
   something `map` assumes (see `docs/adr/0059`).

## Confidence tiers

A `code`/`name` row's `note` is empty: its `target_column` already
encodes the level (e.g. `adm4_name`), and its `unique_count` already
encodes the cardinality signal that used to live in `note`. An
`ambiguous` row has no `target_column`, so its `note` states its tier
and level, plus at most one short clause beyond that, only when it adds
information (see `docs/adr/0060`, `docs/adr/0061`, `docs/adr/0062`).

- `code` / `name`: resolved into the discovered chain by shape and
  position, at a level above admin0.
- `ambiguous`: landed at a chain level above admin0 (or is code-shaped)
  but shape, chain membership, or exact-match priority didn't cleanly
  resolve it.
- `unmatched`: never joined the code chain and never bracketed into any
  level above admin0 (e.g. a free-text `NOTES`/`SOURCE`-style column, or
  any admin0 code/name column, always left unmapped by design); `note`
  is empty.

Every row also carries `unique_count`. For a row bracketed to a level,
it's `COUNT(DISTINCT parent_code, this_column)` against the level above
it, the number of genuinely distinct units once the parent disambiguates
a repeated value (e.g. "County 1" appearing under two different
provinces is 1 raw value but 2 real units). For any other row (level 0,
a code-shaped column outside the chain, or fully `unmatched`), it's the
column's own `COUNT(DISTINCT)`. See `docs/adr/0062`.

## Output ordering

Rows are ordered by resolved level descending (finest first, matching
COD-AB's own "own level, then each ancestor down to admin0" convention),
name before code within a level, then every `unmatched` column last in
the source file's own original column order.

## Not modeled in v1

- Reusing this matching logic from inside `match`/`mosaic`/`clean` isn't
  wired up; nothing currently needs it internally. If that changes, follow
  the precedent `docs/adr/0028` sets for `detect`: extract the shared
  logic into a leaf module first.
- A row-unique non-code column at the exact same cardinality as the
  finest code level (e.g. a raw feature index) can still pass the
  bijection/containment checks and falsely companion with it; noise-
  column exclusion (`core.constants.NOISE_COLUMNS`) mitigates known cases,
  but this is an accepted limitation, not fully closed, same philosophy
  as `docs/adr/0052`.
- A column that genuinely, coincidentally is bijective with a level's
  code (varies 1:1 with it, purely by chance, not because it's the
  level's real name) is numbered and renamed alongside any real name
  candidates there; nothing short of a vocabulary or human signal can
  tell the two apart (`docs/adr/0057`).
- Admin level 0's code/name are never suggested, even when unambiguous;
  a user always fills that one crosswalk row in by hand (`docs/adr/0057`).
- Levels are numbered purely by nesting depth, never a real admin number;
  a source file whose coarsest discovered code column isn't actually
  admin level 0 (e.g. a state-level file with no country column at all)
  still gets that coarsest position excluded, mislabeled as admin0,
  since `map` has no signal left to tell the two cases apart without a
  vocabulary or human input (`docs/adr/0058`).
