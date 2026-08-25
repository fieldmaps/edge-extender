# schema-map

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-map` shares with other tools.

## Inputs

- `schema-map` MUST read the input and reproject it to EPSG:4326 the same way
  every other tool does, via `core.io.read_and_reproject()`.
- `schema-map` MUST take a target-schema YAML file with top-level `name_field`/
  `code_field` string keys, each containing a `{n}` placeholder (e.g.
  `adm{n}_name`/`adm{n}_code`); these supply output naming only, never
  matching vocabulary. If omitted, it MUST default to the bundled generic
  schema (`topo_tools/core/schema_map/data/default.yaml`).
- `schema-map` MUST raise `ValueError` (not a raw `KeyError`/silent empty
  result) if the target-schema YAML is missing either key or either
  value lacks a `{n}` placeholder.
- `schema-map` MUST exclude any column matching `core.constants.is_noise_column()`
  from candidate columns entirely; they never appear in the crosswalk, not
  even as `unmatched`. A column matches if its name, case-insensitively,
  either exactly equals an entry in `core.constants.NOISE_COLUMNS`
  (`objectid`, `globalid`, `shape_leng`/`shape_length`/`shape__length`,
  `shape_area`/`shape__area`, `ogc_fid`/`ogc_fid_orig`/`fid_orig`), or
  equals one after stripping a trailing GDAL collision suffix
  (`_\d+`, e.g. `fid_1` -> `fid`), or is exactly 10 characters long (the
  ESRI Shapefile DBF driver's field-name limit) with that stripped base a
  prefix of a `NOISE_COLUMNS` entry (e.g. `Shape_Le_1` -> `shape_le`, a
  prefix of `shape_length`, the DBF-truncated form of a duplicate field).

## Matching

`schema-map` MUST NOT use any column name, alias, or vocabulary as a matching
signal, and MUST NOT use a value-shape assumption to decide chain
membership either; every candidate column's own values are relationally
tested against every other candidate column's values, never its name.
Value shape (`_looks_code_shaped()`, majority of non-null values
containing a digit) MUST only be consulted as a fallback for the `code`
vs. `name` role of a chain column once its level is already resolved. See
`docs/explanation/schema_map.md` and `docs/adr/0064`, `docs/adr/0066` for the
empirical justification.

- An all-null candidate column (`COUNT(DISTINCT) = 0`) MUST NOT be
  eligible for chain group formation: two all-null columns are trivially,
  vacuously bijective with each other and with nothing else, no real
  evidence either way, the same principle already applied to `_embeds()`
  (see `docs/adr/0069`). It still MUST appear in the crosswalk as
  `unmatched`.
- Every remaining candidate column, code or name alike, MUST be grouped by
  identical `COUNT(DISTINCT)` (constants are kept, not dropped: a
  single-country file's admin0 code is legitimately constant), and
  same-count columns clustered by pairwise verified bijection (two
  columns merge only if bijective with each other; a third column sharing
  their count but not their bijection MUST NOT prevent the other two from
  merging).
- The admin hierarchy MUST be built as the longest path through every
  coarser/finer pair of level-groups that satisfies containment
  (`GROUP BY finer HAVING COUNT(DISTINCT coarser) > 1` MUST return zero
  rows, or exactly one violating group, for every coarser/finer column
  pair between the two groups; see the single-violator tolerance below),
  not just cardinality-adjacent pairs; this lets a finer level reconnect
  past a level that doesn't nest cleanly (a "loose" cross-cutting
  attribute that happens to be embedded inside a compound code, e.g. an
  urban/rural classifier) instead of severing the rest of the chain. A
  candidate edge MUST additionally require either the coarser group's
  `COUNT(DISTINCT)` to be exactly 1 (a true constant, exempt from
  embedding), or some column in the finer group to textually contain
  (`contains(child, parent)`, row for row over non-null pairs, tolerating
  a single violating value) some column in the coarser group, or, if no
  coarser/finer group pair anywhere in the file has embedding evidence at
  all, containment alone (see `docs/adr/0070`). When multiple candidates
  tie for the longest path, the one with more same-level companion
  columns MUST win, then the one with the higher (finer) `COUNT(DISTINCT)`.
- Both the containment and embedding checks above MUST tolerate exactly
  one violating value the same way a NULL already carries no evidence: a
  missing-value sentinel (e.g. `"No_Pcode"`) reused across many real
  parents, never a hardcoded literal, only "exactly one distinct value
  explains every violation". More than one distinct violator MUST fail
  strictly, a genuine multi-value anomaly, not a placeholder (see
  `docs/adr/0071`).
- Every level MUST be numbered by the column's relative rank in the
  discovered chain (0 = coarsest); `schema-map` never takes a real admin number
  as input, it only infers nesting depth.
- Within a resolved chain level, each column's role MUST be `code` if
  either it textually contains (`contains(child, parent)`) some column at
  the level's resolved parent, or it independently passes
  `_looks_code_shaped()`; otherwise it MUST be `name`. This check MUST run
  per column, never deferred to a sibling's embedding result: a column
  that fails to embed its parent MUST still resolve to `code` on its own
  value shape rather than defaulting to `name` just because another
  sibling in the group embedded the parent (see `docs/adr/0067`). Same-
  role companions at one level MUST each get a numbered `target_column`
  from `code_field`/`name_field` (the first by source-column order gets
  the bare rendered template, each next one the template plus an
  appended integer starting at 1).
- Every non-code-eligible column MUST be bracketed into the chain by its
  own `COUNT(DISTINCT)`: it lands at level `k` if `code_count[k-1] <
  distinct_count <= code_count[k]` (`code_count[-1]` is 0); a column
  whose count doesn't fall into exactly one bracket MUST be left
  unmatched.
- A bracketed column MUST additionally pass a same-level function check
  against that level's code column (`GROUP BY code HAVING COUNT(DISTINCT
  candidate) > 1` MUST return zero rows) before it's eligible for
  confidence `name` or `supplemental`; a column that fails this check
  entirely (neither a subset nor superset of the level) MUST be
  confidence `ambiguous`, `target_column` empty.
- A function-passing column MUST be confidence `supplemental`,
  `target_column` empty, when its level's chain group already has a
  resolved `name` role member AND its own collapse ratio (`1 -
  COUNT(DISTINCT candidate) / level_unit_count`) exceeds `0.30`; a
  bijective (exact) same-level companion cannot reach the bracket step at
  all, since bijection would already have merged it into the chain group
  at the grouping step, so a function-passing bracket candidate is always
  a genuine, coarser superset of the level (by pigeonhole, an onto
  function between equal-cardinality sets is also one-to-one, so a
  non-bijective function-passing candidate must be coarser) unless its
  collapse is within that tolerance, in which case it's treated as a
  same-level translation/transcription variant instead (see
  `docs/adr/0076`). When the level's chain group has no `name` role
  member yet, or the candidate's collapse ratio is `<= 0.30`,
  function-passing candidates MUST instead resolve to confidence `name`,
  numbered `target_column` from `name_field` (same numbering scheme as
  code companions above).
- A column landing in no bracket at all MUST be confidence `unmatched`,
  `target_column` and `note` both empty.
- A resolved level MUST be excluded from output (fall through to
  confidence `unmatched`) only when its own `COUNT(DISTINCT)` is exactly
  1, a true constant; a non-constant level MUST be resolved regardless of
  its rank in the discovered chain, even at position 0. `schema-map` has no way
  to tell a genuine admin0 constant from a coarsest-in-file level that
  merely isn't actually admin0 (a file with no country column at all); it
  only excludes columns with no real variation to report.
- `target_column` MUST be non-empty only for a `code`/`name` row; every
  `ambiguous`/`unmatched` row's `target_column` MUST be empty, since
  `schema-refactor` drops any source column whose crosswalk `target_column` is
  empty (see `docs/reference/schema_refactor.md`) and a human, not `schema-map`,
  decides whether to keep such a column and under what name.
- `schema-map` MUST NOT call an LLM or any external service; matching is
  embedding and cardinality/containment logic only.

## Outputs

- `schema-map` performs no topology hard gate at all; it only inspects and
  never mutates geometry.
- `schema-map` MUST always produce a crosswalk file, one CSV row per source
  column with exactly four columns: `source_column`, `target_column`,
  `unique_count`, `note`. Every row MUST carry a `unique_count`: for a
  row bracketed to a level (`code`, `name`, `ambiguous`, or
  `supplemental`), `COUNT(DISTINCT parent_code, this_column)` against
  the level above it, catching a value reused across parents (e.g.
  "County 1" under two different provinces) that a same-column distinct
  count alone would hide; for any other row (an excluded constant level,
  or fully `unmatched`), the column's own `COUNT(DISTINCT)`. A
  `code`/`name` row's `note` MUST be empty, since `target_column` already
  encodes the level and `unique_count` already encodes the cardinality
  signal. A bracketed `ambiguous` row's `note` MUST be exactly
  `"ambiguous, level {k}"`; a bracketed `supplemental` row's `note` MUST
  be exactly `"supplemental, superset of level {k}"`. An `unmatched`
  row's `note` MUST be empty.
- Rows MUST be ordered by resolved level descending (finest first,
  matching COD-AB's own-level-then-ancestors order), name before code
  within a level, then every `unmatched` column last in the source
  file's own column order.
- `schema-map` MUST NOT rename or drop any column in the input file itself
  (see `docs/reference/schema_refactor.md` for the tool that does).

## Configuration (`api.schema_map.map()` / CLI)

- `schema-map` MUST process exactly one input file per call.
- The crosswalk path MUST default to the input path with a `_crosswalk`
  stem suffix and a `.csv` extension.
- `schema-map` MUST raise `FileExistsError` if the output path already exists
  and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `schema-map`, `outputs`; any
  other value MUST raise `ValueError`.
