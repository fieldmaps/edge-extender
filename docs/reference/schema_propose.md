# schema-propose

See `docs/reference/README.md` for the MUST/SHOULD/MAY convention, and
`docs/reference/shared.md` for rules `schema-propose` shares with other
tools.

## Inputs

- `schema-propose` MUST read the input and reproject it to EPSG:4326 the
  same way every other tool does, via `core.io.read_and_reproject()`.
- `schema-propose` MUST take a target-schema YAML file describing canonical
  target fields (name, optional `aliases`, optional regex `patterns`,
  optional `repeatable: {min, max}` for an admin-level field family like
  `adm{n}_name`).
- `schema-propose` MUST raise `ValueError` (not a raw `KeyError`/silent
  empty result) if the target-schema YAML is missing its top-level
  `fields` key, if a field entry is missing `name`, or if a `repeatable`
  block is missing `min`/`max`.

## Matching

- A source column MUST be claimed by the first field (in target-schema
  declaration order) whose exact name or alias it matches, confidence
  `exact`.
- A repeatable field's literal rendered name at a specific level (e.g.
  `adm2_pcode`) MUST also count as an `exact` match at that level.
- A source column not exactly matched, but matching a repeatable field's
  alias or regex pattern with the level unresolved, MUST be grouped with
  every other such candidate for that same field into one candidate set.
- A candidate set of two or more columns MUST be ordered coarsest-to-finest
  by `COUNT(DISTINCT column)`, then validated: every adjacent pair MUST
  have strictly unequal distinct counts, and every value of the finer
  column MUST map to exactly one value of the coarser column (`GROUP BY
  finer HAVING COUNT(DISTINCT coarser) > 1` MUST return zero rows). If the
  whole chain validates, the finest column MUST resolve to an exact level
  when `own_level` is given (confidence `exact`); every other column in
  the chain MUST be confidence `nesting-validated-relative`, with
  `target_column` set to its own original name (retained, not dropped)
  pending a human-assigned level number. If any pair in the chain fails to
  validate, every column in that candidate set MUST be confidence
  `ambiguous` instead, none of them auto-resolved.
- `own_level` MUST be validated against the matched field's declared
  `repeatable` range; a value outside that range MUST raise `ValueError`.
- A source column not exactly matched, but matching a non-repeatable
  field's regex pattern, MUST be claimed at confidence `pattern`.
- A source column matching nothing at all MUST be confidence `unmatched`,
  with `target_column` set to its own original name (retained, not
  dropped) pending review.
- `schema-propose` MUST NOT call an LLM or any external service; matching
  is exact/alias/pattern/cardinality logic only.

## Outputs

- `schema-propose` performs no topology hard gate at all; it only inspects
  and never mutates geometry.
- `schema-propose` MUST always produce a crosswalk file, one JSON object
  per source column with `source_column`, `target_column`, `confidence`,
  and `note` keys, in the source file's own column order.
- `schema-propose` MUST NOT rename or drop any column in the input file
  itself (see `docs/reference/schema_apply.md` for the tool that does).

## Configuration (`api.schema_propose.schema_propose()` / CLI)

- `schema-propose` MUST process exactly one input file per call.
- The crosswalk path MUST default to the input path with a `_crosswalk`
  stem suffix and a `.json` extension.
- `schema-propose` MUST raise `FileExistsError` if the output path already
  exists and overwriting wasn't requested.
- `own_level`, if given, MUST be a non-negative integer; a negative value
  MUST raise `ValueError`.
- `step`, if given, MUST be one of `inputs`, `propose`, `outputs`; any
  other value MUST raise `ValueError`.
