# dissolve

Aggregates a polygon layer into a coarser one by grouping on attribute
columns and unioning geometry per group. Every column not in `--group-by`
is kept automatically if it's constant per group, dropped with a warning
if not. `dissolve` is scoped to boundary topology only, no attribute
aggregation (sum a population count as a separate step).

### Example 1: dissolve one level up

Only the grouping key needs naming: constant ancestor columns
(`adm1_pcode`, `adm2_name`) are kept automatically, admin3's own columns
are dropped automatically.

    topo-tools dissolve adm3.geojson adm2.geojson --group-by adm2_pcode

Add ancestor pcodes too (`adm2_pcode,adm1_pcode`) if `adm2_pcode` alone
isn't guaranteed unique, to avoid silently merging two distinct units.

### Example 2: build a full admin hierarchy from one finest layer

Each level dissolves independently from the same finest file, not chained
from the previous output. Passing `--target-schema` once auto-excludes
every column finer than each call's own `--group-by` level (e.g. admin3's
`adm3_name1`/`adm3_name2` alt-language columns from the admin2 output, plus
admin2's own columns too from the admin1/admin0 outputs), instead of a
hand-maintained `--exclude` list per call:

    topo-tools dissolve adm3.parquet adm2.parquet --group-by adm2_pcode --target-schema schema.yaml
    topo-tools dissolve adm3.parquet adm1.parquet --group-by adm1_pcode --target-schema schema.yaml
    topo-tools dissolve adm3.parquet adm0.parquet --group-by adm0_pcode --target-schema schema.yaml

Leaf-level data with NULL deeper-level id/name columns (e.g. countries whose
source doesn't reach admin3) needs those columns filled down from the
nearest shallower level before this grouping works; `schema-fill`
(`docs/tutorials/schema_fill.md`) fills them down and stamps each row's
real depth first, then each level above dissolves normally as shown here.

### Example 3: drop a known column without a target schema

For a one-off case, `--exclude` drops named columns unconditionally, no
schema file needed:

    topo-tools dissolve adm3.geojson adm2.geojson --group-by adm2_pcode --exclude adm3_name1,adm3_name2
