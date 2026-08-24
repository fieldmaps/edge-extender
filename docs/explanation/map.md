# Map Explanation

`map` reads a source file's columns and a target-schema config (a bundled
default, or user-supplied), and maps a source-column -> canonical-column
crosswalk, without touching the file. It replaces what `hdx-cod-ab-ai`
previously did by having a live Claude Code session freehand DuckDB
`DESCRIBE` queries and its own judgment: matching here is embedding and
cardinality/containment logic only, with no LLM call and no column-name
vocabulary anywhere, so it's reusable outside an agentic session and the
matching decisions are inspectable, versionable, and reproducible.
`hdx-cod-ab-ai`'s PRD requires that no stage ever auto-applies without a
human confirming it first (see its "no auto-approve mode" requirement);
`map` never renames anything itself, it only writes a crosswalk for a
human to review, edit, and hand to `refactor`
(`docs/explanation/refactor.md`).

## Why column names, and value shape, are never a matching signal

Real source files never reliably use a target schema's vocabulary: a
GRID3 health-zone layer uses French field names, a national mapping
agency's shapefile uses its own local convention, and no alias/pattern
list can anticipate every source vocabulary in advance. Treating column
names as signal is unreliable by construction, not just under-tuned. See
`docs/adr/0054` for the empirical evidence (a real Madagascar admin4
shapefile) that motivated replacing the earlier name/alias/pattern-based
design.

A value-shape assumption fails the same way for *deciding what nests
where*: real national source files use pure-numeric codes, pure-alpha
codes, compound codes with a prefix longer than COD-AB's own convention,
and opaque GRID3 GUIDs, none of which match COD-AB's own p-code shape.
What every admin boundary file *does* share, regardless of vocabulary or
shape, is a purely relational fact: a hierarchy nests (each finer unit
belongs to exactly one coarser unit), and a real hierarchical code is
often (not always) *constructed* from its parent's code, so it textually
contains that parent's value. `map` never uses column name or value
shape to decide chain membership or level; it uses value shape only as a
last-resort fallback for one narrower question, once a level is already
resolved by nesting: does *this* column at *that* level play the `code`
or `name` role, when nothing in the level embeds its parent to settle it
directly (see `docs/adr/0064`, `docs/adr/0066`).

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
   (`core.constants.is_noise_column()`, catching both an exact
   `NOISE_COLUMNS` name and a GDAL collision-suffixed or DBF-truncated
   form of one, e.g. `fid_1` or `Shape_Le_1`), shape-classifies and
   structurally positions every remaining source column (below), reorders
   everything, and writes one crosswalk row per column (`{name}_02`).
3. **`_03_outputs`**: exports `{name}_02` as the crosswalk CSV file. No
   hard gate: like `detect`, this tool never modifies geometry, so there's
   nothing to validate against.

## Algorithm

1. **Group every column, code or name alike, by cardinality and
   bijection** (`_build_level_groups()`, `core/map/_02_map.py`): no
   pre-filter decides code-vs-name eligibility up front, since a real
   file may use codes to build the chain at one level and names at
   another, and admin1 (not admin0) may be the first level with any real
   nesting at all. Columns sharing a `COUNT(DISTINCT)` cluster together
   only if pairwise bijective with each other (a third column sharing
   their count but not their bijection stays its own singleton, it
   doesn't break the other two apart). An all-null column (`COUNT
   (DISTINCT) = 0`) is excluded from this step entirely: two all-null
   columns are vacuously bijective with each other and with nothing else,
   no real evidence either way, the same principle `_embeds()` already
   applies (see `docs/adr/0069`). It still appears in the crosswalk,
   correctly falling through to `unmatched`.
2. **Build the hierarchy as a longest path over the full containment
   DAG, embedding-justified except at a true constant**
   (`_build_chain()`, `core/map/_02_map.py`): dynamic programming over
   every coarser/finer pair of groups, not just cardinality-adjacent
   ones, testing that `GROUP BY finer HAVING COUNT(DISTINCT coarser) > 1`
   returns zero rows, or exactly one violating group, for each
   (containment), and additionally requiring either the coarser group's
   `COUNT(DISTINCT)` to be exactly 1 (a constant has no variation to test
   embedding against, so it's exempt), or some column in the finer group
   to textually contain (`contains(child, parent)`) some column in the
   coarser group, tolerating one violating value the same way, or, when
   no group pair anywhere in the file embeds at all, containment alone
   (DRC's GRID3 health-facility layers nest `province` through `airesante`
   by name only, no compound code anywhere, see `docs/adr/0070`). The
   single-violator tolerance (both here and in step 1's bijection check)
   catches a missing-value sentinel like Syria's `"No_Pcode"`, reused
   across many real parents, never a hardcoded literal: exactly one
   distinct value must explain every violation, or the check stays strict
   (Syria's `Admin_Unit.shp` has `SY14` genuinely duplicating five other
   governorates' district codes, a real multi-value anomaly, not a
   placeholder, so it correctly stays unresolved, see `docs/adr/0071`).
   Testing every pair, not just neighbors, lets a finer level reconnect
   past one that doesn't nest cleanly: a "loose" cross-cutting attribute
   can still get baked into a compound code's construction (an urban/rural
   classifier concatenated into a barrio-level code, say) without
   breaking the chain around it. When multiple candidates tie for the
   longest path, the one with more same-level companion columns wins (a
   code+name pair beats a lone column), then the one with the higher
   (finer) `COUNT(DISTINCT)` (see `docs/adr/0066`); this is what lets a
   real, bijective code+name pair (Madagascar's `ADM1_PCODE`+`ADM1_EN`)
   win a chain slot over a coarser, independently-numbered grouping that
   also reaches the same root (`PROV_CODE_`) at the same path length.
3. **Assign each chain level's columns a `code`/`name` role,
   per column, never deferred to a sibling** (`_assign_chain_roles()`): a
   column that embeds its level's resolved parent is `code`; otherwise
   its own value shape decides (`_looks_code_shaped()`, a majority of
   non-null values containing a digit), independently of whether some
   other column at the same level embedded the parent. A column that
   fails to embed the parent still resolves to `code` on shape alone
   rather than defaulting to `name`: a companion group can have more than
   one real code representation (Angola's numeric `Cod_Prov` alongside
   its embedding `Cod_Alfa_N`), and a coincidentally bijective non-name
   attribute (Mozambique's numeric `area_sqkm`, sharing a level's
   cardinality by chance) must not claim the `name` slot away from the
   level's real name column just because it failed to embed (see
   `docs/adr/0067`).
4. **Bracket every non-chain column into the chain by cardinality**
   (`_bracket_other_columns()`): a column lands at chain level `k` if
   `code_count[k-1] < COUNT(DISTINCT col) <= code_count[k]`
   (`code_count[-1]` is 0). A column whose count doesn't fall into
   exactly one bracket is left unmatched. A bracketed column additionally
   passes a same-level function check against that level's code column
   (`GROUP BY code HAVING COUNT(DISTINCT candidate) > 1` returns zero
   rows, i.e. every code value maps to exactly one value of the
   candidate): real name columns fail a direct containment check against
   a *different* level's code (the same name legitimately repeats under
   different parents), but must pass it against their *own* level's
   code, since a given unit's code always has exactly one name. A
   bijective (exact) same-level companion can never reach this bracket
   step at all: bijection would already have merged it into the chain
   group at the grouping step (step 1). So a function-passing bracket
   candidate is always a genuine, coarser (superset) grouping over the
   level, never a same-level near-tie: by pigeonhole, an onto function
   between equal-cardinality sets is automatically one-to-one too, so a
   non-bijective function-passing candidate can't have the level's own
   cardinality. When the level's chain group already has a resolved
   `name` role member, a function-passing candidate becomes
   `supplemental` (see `docs/adr/0065`); when it doesn't yet, the
   function-passing candidate resolves to `name` directly. A bracketed
   column that fails the function check entirely (neither a subset nor
   superset of the level) stays `ambiguous`.
5. **Number and emit rows**: a chain position's level number is always
   its relative rank (0 = coarsest). `map` never takes a real admin
   number as input, it only infers nesting depth (see `docs/adr/0058`).
   Every code-chain column and every winning bracketed name column
   becomes a `code`/`name` row, `target_column` always rendered from the
   schema template at that level; when two or more qualify at the same
   level and role (bijective companions, or multiple function-passing
   name matches), each is numbered by source-column order, the first
   getting the bare template (`adm2_name`, `adm2_pcode`) and each next
   one the template plus an appended integer (`adm2_name1`,
   `adm2_pcode1`, ...) (see `docs/adr/0056`). **A resolved level is
   excluded from output only when its own `COUNT(DISTINCT)` is exactly
   1**, a true constant; a non-constant level is resolved regardless of
   its rank in the chain, even at position 0 (see `docs/adr/0066`, which
   drops ADR-0057's position-based admin0 exclusion: `map` has no country
   column to assume, so it can't tell a genuine admin0 constant from a
   coarsest-in-file level that merely isn't actually admin0). Everything
   else becomes `supplemental` (a bracketed column that's a confirmed
   coarser grouping over the level, see `docs/adr/0065`), `ambiguous`
   (bracketed but failing the function check entirely), or `unmatched`,
   `target_column` left empty in every case: `refactor` drops a column
   whose crosswalk `target_column` is empty, so keeping one under its
   own name is a decision a human makes by editing the crosswalk, not
   something `map` assumes (see `docs/adr/0059`).

## Confidence tiers

A `code`/`name` row's `note` is empty: its `target_column` already
encodes the level (e.g. `adm4_name`), and its `unique_count` already
encodes the cardinality signal that used to live in `note`. An
`ambiguous`/`supplemental` row has no `target_column`, so its `note`
states its tier and level, in one of two fixed forms: `"ambiguous, level
{k}"` or `"supplemental, superset of level {k}"` (see `docs/adr/0065`,
`docs/adr/0066`).

- `code` / `name`: resolved into the discovered chain by embedding (or,
  absent embedding evidence, value shape) and position; a level resolves
  regardless of its rank, unless it's a true constant.
- `supplemental`: bracketed at a resolved chain level, function-passing
  against that level's code, but a confirmed coarser (superset) grouping
  rather than the level's own code/name, because the level's chain group
  already has a resolved `name` (see `docs/adr/0065`, `docs/adr/0066`).
- `ambiguous`: landed at a resolved chain level but failed the function
  check entirely (neither a subset nor superset of the level).
- `unmatched`: never joined the chain and never bracketed into any
  resolved level (e.g. a free-text `NOTES`/`SOURCE`-style column, or any
  column whose only resolvable level is a true constant); `note` is
  empty.

Every row also carries `unique_count`. For a row bracketed to a level,
it's `COUNT(DISTINCT parent_code, this_column)` against the level above
it, the number of genuinely distinct units once the parent disambiguates
a repeated value (e.g. "County 1" appearing under two different
provinces is 1 raw value but 2 real units). For any other row (an
excluded constant level, or fully `unmatched`), it's the column's own
`COUNT(DISTINCT)`. See `docs/adr/0062`.

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
  column exclusion (`core.constants.is_noise_column()`) mitigates known
  GIS bookkeeping cases (including a GDAL collision-suffixed or
  DBF-truncated duplicate, see `docs/adr/0068`), but this is an accepted
  limitation for any other coincidentally row-unique attribute, not fully
  closed, same philosophy as `docs/adr/0052`.
- A column that genuinely, coincidentally is bijective with a level's
  code (varies 1:1 with it, purely by chance, not because it's the
  level's real name) is numbered and renamed alongside any real name
  candidates there; nothing short of a vocabulary or human signal can
  tell the two apart (`docs/adr/0057`).
- A code column with no parent-value embedding evidence, at a level whose
  parent isn't a true constant, chains only if no group pair anywhere in
  the file embeds at all (`docs/adr/0070`); a genuinely mixed file (some
  levels use compound codes, this one doesn't, e.g. an independently-
  assigned per-level code convention alongside a real p-code elsewhere)
  still leaves that one level unresolved rather than guessing, since
  containment alone can't distinguish a real nesting relationship from
  coincidence once embedding evidence exists elsewhere in the same file
  (`docs/adr/0064`, `docs/adr/0066`).
- Levels are numbered purely by nesting depth, never a real admin number.
  A source file whose coarsest discovered level isn't actually admin0
  (e.g. a state-level file with no country column at all) still gets that
  coarsest position resolved and numbered as if it were admin0, since
  `map` has no signal left to tell the two cases apart without a
  vocabulary or human input; a human renames it by hand in the crosswalk
  (`docs/adr/0058`, `docs/adr/0066`).
