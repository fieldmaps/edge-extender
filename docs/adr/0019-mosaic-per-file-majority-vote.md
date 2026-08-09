# 0019: Per-file majority-vote assignment, not per-child plurality

## Status

Accepted.

## Context

`mosaic` assigns children against already-extended geometry, which can be
dramatically larger than the original footprint: Chile admin3's
`extended.parquet` measured at roughly 200x the area of the original layer,
with a bounding box spanning most of the South Pacific. That scale of
overshoot is `extend()`'s normal, intended output, not a data error, but it
means a per-child plurality-of-shared-area rule (assign each child
independently to whichever parent it shares the most overlap area with) can
be wrong at the edges: combining 8 West Africa countries'
`extended.parquet` layers under a naive per-child rule produced 19 real
coverage gaps (up to 0.57 sq degrees, in Togo), each traced to a single
border-adjacent admin2 child whose overshoot gave a neighboring country's
parent more overlap *area* than its own (e.g. a Côte d'Ivoire unit landing
on Ghana). Per-child plurality alone can't distinguish "genuine outlier"
from "truly belongs to the neighbor."

## Decision

`_02_assign` assigns every child in one source file to a single, shared
parent chosen by majority vote across that file's children (count of
children intersecting each candidate parent, not summed overlap area), not
independently per child. A country's interior children, unaffected by
border overshoot, still overwhelmingly vote for their true parent by count,
so a handful of border-overshooting children can no longer misassign the
whole file. A tie falls back to the lower parent id.

## Consequences

The residual risk is a file with too few children to form a real majority:
a single-child file has no other vote to correct it, and a genuinely tied
vote falls back to parent id rather than any geometric signal, not a
guarantee of correctness. This is `mosaic`-specific: `match` never sees
this failure mode, since it assigns against tight, pre-extension geometry
where overshoot doesn't exist yet.
