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
from the previous output.

    topo-tools dissolve adm3.parquet adm2.parquet --group-by adm2_pcode
    topo-tools dissolve adm3.parquet adm1.parquet --group-by adm1_pcode
    topo-tools dissolve adm3.parquet adm0.parquet --group-by adm0_pcode
