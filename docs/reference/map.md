# map

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `map` shares with other tools.

## Inputs

- `map` MUST read the input and reproject it to EPSG:4326 the same way
  every other tool does, via `core.io.read_and_reproject()`.
- `map` MUST take a target-schema YAML file with top-level `name_field`/
  `code_field` string keys, each containing a `{n}` placeholder (e.g.
  `adm{n}_name`/`adm{n}_pcode`); these supply output naming only, never
  matching vocabulary. If omitted, it MUST default to the bundled COD-AB
  schema (`topo_tools/core/map/data/cod-ab.yaml`).
- `map` MUST raise `ValueError` (not a raw `KeyError`/silent empty
  result) if the target-schema YAML is missing either key or either
  value lacks a `{n}` placeholder.
- `map` MUST exclude `core.constants.NOISE_COLUMNS` (case-insensitive:
  `objectid`, `globalid`, `shape_leng`/`shape_length`/`shape__length`,
  `shape_area`/`shape__area`, `ogc_fid`/`ogc_fid_orig`/`fid_orig`) from
  candidate columns entirely; they never appear in the crosswalk, not
  even as `unmatched`.

## Matching

`map` MUST NOT use any column name, alias, or vocabulary as a matching
signal; every candidate column's own values are shape-classified and
structurally positioned, never its name. See `docs/explanation/map.md`
for the empirical justification.

- Every candidate column MUST be shape-classified by a majority-vote
  match rate against COD-AB's own p-code format (`^[A-Za-z]{1,4}[0-9]+$`,
  letter prefix plus digit suffix): `code` at or above a 75% match rate,
  `name` at or below 10%, `ambiguous` otherwise. A constant (distinct
  count 1) column whose sole value is bare uppercase letters
  (`^[A-Z]{1,4}$`) MUST be reclassified `code`-shaped too (a bare ISO2/3
  country code, COD-AB's admin0 pcode convention, has no digit suffix).
- Code-shaped columns MUST be grouped by identical `COUNT(DISTINCT)`
  (constants are kept, not dropped: a single-country file's admin0 code
  is legitimately constant), same-count groups verified truly bijective
  before treating them as same-level companions (a group that fails MUST
  be demoted to singleton columns, not discarded), then chained
  coarsest-to-finest via containment (`GROUP BY finer HAVING
  COUNT(DISTINCT coarser) > 1` MUST return zero rows), splitting into
  independent chains at any failed adjacent pair. The longest resulting
  chain MUST be treated as the discovered admin hierarchy; a code-shaped
  column outside that chain MUST be confidence `ambiguous`.
- Every level MUST be numbered by the column's relative rank in the
  discovered code chain (0 = coarsest); `map` never takes a real admin
  number as input, it only infers nesting depth.
- Every code-chain column MUST be confidence `code`. Same-count bijective
  code companions at one level MUST each get a numbered `target_column`
  from `code_field` (the first by source-column order gets the bare
  rendered template, each next one the template plus an appended integer
  starting at 1).
- Every non-code-shaped (name-shaped or shape-ambiguous) column MUST be
  bracketed into the code chain by its own `COUNT(DISTINCT)`: it lands at
  level `k` if `code_count[k-1] < distinct_count <= code_count[k]`
  (`code_count[-1]` is 0); a column whose count doesn't fall into exactly
  one bracket MUST be left unmatched.
- A bracketed, name-shaped column MUST additionally pass a same-level
  function check against that level's code column (`GROUP BY code HAVING
  COUNT(DISTINCT candidate) > 1` MUST return zero rows) before it's
  eligible for confidence `name`. A function-passing column that's also
  bijective with the level's code (every candidate value maps back to
  exactly one code value too) is an exact match; when at least one exact
  match exists at a level, only exact matches MUST resolve to `name`,
  every other function-passing candidate there MUST be confidence
  `ambiguous`, its note naming the exact match.
- Every bracketed column at a level that resolves (per the exact-match
  priority above) MUST be confidence `name`, with a numbered
  `target_column` from `name_field` at its bracketed level (same
  numbering scheme as code companions above).
- A bracketed column that is shape-ambiguous, is name-shaped but fails
  the function check, or loses to an exact match, MUST be confidence
  `ambiguous`, `target_column` empty.
- A column landing in no bracket at all MUST be confidence `unmatched`,
  `target_column` and `note` both empty.
- Admin level 0 MUST never be resolved: `map` MUST NOT emit a `code` or
  `name` row for any column whose resolved level is `0`, regardless of
  how unambiguous the match would otherwise be; such a column MUST fall
  through to confidence `unmatched` instead.
- `target_column` MUST be non-empty only for a `code`/`name` row; every
  `ambiguous`/`unmatched` row's `target_column` MUST be empty, since
  `refactor` drops any source column whose crosswalk `target_column` is
  empty (see `docs/reference/refactor.md`) and a human, not `map`,
  decides whether to keep such a column and under what name.
- `map` MUST NOT call an LLM or any external service; matching is
  value-shape and cardinality/containment logic only.

## Outputs

- `map` performs no topology hard gate at all; it only inspects and
  never mutates geometry.
- `map` MUST always produce a crosswalk file, one CSV row per source
  column with exactly four columns: `source_column`, `target_column`,
  `unique_count`, `note`. Every row MUST carry a `unique_count`: for a
  row bracketed to a level (`code`, `name`, or `ambiguous` with a level),
  `COUNT(DISTINCT parent_code, this_column)` against the level above it,
  catching a value reused across parents (e.g. "County 1" under two
  different provinces) that a same-column distinct count alone would
  hide; for any other row (level 0, a code-shaped column outside the
  chain, or fully `unmatched`), the column's own `COUNT(DISTINCT)`. A
  `code`/`name` row's `note` MUST be empty, since `target_column` already
  encodes the level and `unique_count` already encodes the cardinality
  signal; an `ambiguous` row's `note` MUST start with its tier followed
  by its level (it has no `target_column` to encode the level), plus at
  most one short clause beyond that, only when it adds information; an
  `unmatched` row's `note` MUST be empty.
- Rows MUST be ordered by resolved level descending (finest first,
  matching COD-AB's own-level-then-ancestors order), name before code
  within a level, then every `unmatched` column last in the source
  file's own column order.
- `map` MUST NOT rename or drop any column in the input file itself
  (see `docs/reference/refactor.md` for the tool that does).

## Configuration (`api.map.map()` / CLI)

- `map` MUST process exactly one input file per call.
- The crosswalk path MUST default to the input path with a `_crosswalk`
  stem suffix and a `.csv` extension.
- `map` MUST raise `FileExistsError` if the output path already exists
  and overwriting wasn't requested.
- `step`, if given, MUST be one of `inputs`, `map`, `outputs`; any
  other value MUST raise `ValueError`.
