# 0054: `map` drops name/vocabulary matching entirely, structural discovery only

## Status

Accepted. Supersedes ADR-0052's exact/alias/pattern/nesting/structural
five-pass design (that ADR stays as the historical record of the earlier
approach; it is not edited).

## Context

`map` was tested against a real Madagascar admin4 shapefile
(`mdg_admbnda_adm4_BN_Cleaned_revised.shp`, 17,465 rows) against a
hand-built reference crosswalk. Results were poor even though ADR-0052's
structural-discovery pass existed as a fallback: exact/alias/pattern
matching against `cod-ab.yaml`'s vocabulary claimed some columns
correctly but missed most of the real hierarchy, and a row-unique
GDAL-synthesized `OGC_FID` column falsely "contained" the finest-level
pcode column, since containment against a row-unique column is trivially
satisfied by anything.

Direct queries against the real data (not recalled, tested this session)
showed:

- Code columns (`ADM0_PCODE`..`ADM4_PCODE`) behave cleanly: strictly
  increasing distinct counts (1, 24, 120, 1645, 17465) and near-perfect
  parent-code prefix nesting (0, 0, 192, 3 violations out of 17,465 rows;
  the 192/3 are a real, source-documented exception where some district
  codes reuse their parent commune's code with an `'A'` suffix).
- Name columns (`ADM0_EN`..`ADM4_EN`) do not: distinct counts (1, 24,
  120, 1486, 10977) are lower than their matching code counts at levels
  3-4, because real names repeat across different parents (113 and 2,045
  confirmed cross-parent duplicates). A containment/bijection check
  against these names directly fails; only cardinality bracketing against
  an already-established code chain recovers them, and it correctly
  recovers all 5 levels on this data.
- A naive code-shape regex (alphanumeric, no whitespace) false-positives
  on 3,442 of 17,465 real name values (single-word place names). A regex
  matching COD-AB's own documented p-code format instead
  (`^[A-Za-z]{1,4}[0-9]+$`, letter prefix plus digit suffix) matches 0
  name values and the large majority of code values, confirming a
  majority-vote threshold, not exact match, is the right decision rule.

This confirmed the underlying premise of ADR-0052's design, exact/alias/
pattern matching by column name as the primary mechanism with structural
detection as a fallback, was backwards, not just under-tuned: a source
file's column names are unreliable signal by construction (no vocabulary
list can anticipate every source convention), while value shape and
cardinality/containment are reliable regardless of naming.

## Decision

Delete exact/alias/pattern/nesting-by-repeatable-field matching entirely.
`map` now runs one structural pipeline, unconditionally, on every
non-noise candidate column:

1. Shape-classify every column by majority-vote match rate against the
   p-code regex above: `code` at or above 75%, `name` at or below 10%,
   `ambiguous` otherwise.
2. Build the code-only hierarchy chain from code-shaped columns only
   (reusing ADR-0052's group-by-cardinality + bijection + containment
   machinery, unchanged), keeping constant columns this time (a
   single-country file's admin0 code is legitimately constant, unlike the
   general structural case ADR-0052 handled).
3. Bracket every name-shaped/ambiguous column into the chain by
   cardinality range (`code_count[k-1] < distinct_count <= code_count[k]`),
   since real names fail direct containment but not bracketing.
4. `--own-level` anchors the whole combined chain's finest level once,
   replacing the old per-repeatable-field anchoring.

Confidence tiers drop from seven to five: `code`, `name`, `ambiguous`,
`missing` (gap row, only when `--own-level` given), `unmatched`.

The target-schema YAML format is a breaking change: `fields`/`aliases`/
`patterns`/`repeatable` are gone, replaced by two templates,
`name_field`/`code_field`. The 7 non-hierarchy COD-AB fields
(`iso2`/`iso3`/`valid_on`/`valid_to`/`area_sqkm`/`version`/`lang`) are
dropped from the bundled schema entirely: none of them have hierarchy
structure to position them by, so this design has no way to place them.

`core.constants.NOISE_COLUMNS` gains `ogc_fid`/`ogc_fid_orig`/`fid_orig`
(GDAL's own synthesized feature index), addressing the false-companion
case found in the MDG data directly, the same noise-exclusion mechanism
ADR-0052 already established for `OBJECTID`-style columns.

## Consequences

Any custom `--target-schema-file` written against the old `fields`/
`aliases`/`patterns`/`repeatable` format breaks and must be rewritten to
the new two-key format.

`map` can no longer place a field with no cardinality signature of its
own (a constant per-file attribute like a source/version tag) anywhere in
the hierarchy; such fields are out of scope for this design, not a
regression, since ADR-0052's alias-based matching couldn't robustly infer
them from real data either.

A row-unique non-code column at a code level's exact cardinality can
still, in principle, falsely bijection-match and companion with it; this
is the same accepted limitation ADR-0052 documented, mitigated by human
review via crosswalk notes, not fully closed.
