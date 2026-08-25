# 0078: `edge-mosaic`'s gap-fill passthrough is opt-in and edge-mosaic-only

## Status

Superseded by ADR-0083: the passthrough entity was found to be the wrong
one (child-orphan, not parent-orphan).

## Context

Combining many per-country already-extended files into one global adm0
layer via `edge-mosaic` silently drops any country whose file has no
overlap at all with the parent/clip layer (a country genuinely missing
from that global adm0 source). `assign_one` already routes every child of
such a file into `_02_unassigned`, and `edge-mosaic` already reports it as
an `unassigned` issues-report row; the gap is that there is no way to keep
that country's own already-extended geometry in the final output instead
of losing it.

Only `edge-mosaic`'s children are contractually guaranteed to already be a
complete, valid coverage layer (a finished `edge_extend()` output). That
guarantee is what makes an unclipped passthrough safe: the geometry being
kept has already passed `edge-extend`'s own zero-tolerance gap check. Raw
`edge-clip`/`edge-match` children carry no such guarantee, so the same
passthrough would risk introducing genuinely invalid coverage into an
output that presents itself as clipped/matched.

`_02_unassigned` conflates two different situations: a whole file with no
parent overlap at all, and an individual child dropped from an otherwise-
matched file (an already-documented, intentional behavior, see
`core.assign`'s majority-vote design). Only the first situation is safe to
passthrough; rescuing an individual child would put unclipped geometry
directly alongside its own clipped siblings from the same file, which
`core.assign`'s per-file vote already decided didn't belong there.

## Decision

1. `on_unmatched: str = "drop"` is added to `api.edge_mosaic.mosaic()`,
   validated against `("drop", "passthrough")` the same way `step` is
   validated; the CLI exposes it as `--on-unmatched [drop|passthrough]`,
   default `drop`. The default behavior is unchanged; passthrough is
   strictly opt-in.
2. Passthrough scope is whole-file only, computed as a set difference of
   distinct `source_file` between `{name}_child_01` and
   `{name}_child_01 JOIN {name}_02_assign`, inside
   `core/edge_mosaic/_01_clip.py` (not inside `core.assign`, which has no
   file/child distinction to draw this line and must stay a neutral leaf
   shared by every caller).
3. Passthrough children are unioned into `{name}_03` via `UNION ALL BY
   NAME`, the same idiom already used elsewhere in this codebase
   (`core/assign/_inputs.py::load_children`,
   `_03_outputs.py::_build_issues`) to reconcile tables with differing
   columns. This fills `parent_fid` and any carried columns (ADR-0077) as
   NULL for passthrough rows automatically, with no fallback join against
   a separate reference source; enrichment for gap-filled countries is
   deliberately out of scope here (see ADR-0077's Consequences).
4. No change to `edge_stitch`: passthrough rows enter before the whole-
   table `ST_CoverageClean` pass, so any seam between an unclipped
   country and its clipped neighbors gets the same chance to resolve as
   every other cross-provenance seam already does; `check_valid_topology`
   still raises if it can't.
5. `core/edge_mosaic/_03_outputs.py` excludes passthrough children from
   `unassigned` issue rows and adds a distinct `kind='passthrough'` row per
   passthrough child instead, since `unassigned`'s documented meaning
   ("didn't make it into the output") is actively false for these rows.
   `reason` is populated the same way code-join issue rows already
   populate it.

## Consequences

A country whose file has zero overlap with the parent layer keeps its own
already-extended geometry in the output when `--on-unmatched passthrough`
is set, with no attribute enrichment (NULL carried columns) unless a
future reference-based backfill is built separately. An individual child
dropped from an otherwise-matched file is unaffected either way, it stays
dropped and reported as `unassigned`, regardless of `on_unmatched`.
`edge-clip` and `edge-match` gain no equivalent flag; their children carry
no completeness guarantee that would make an unclipped passthrough safe,
and extending this pattern to either would need its own justification.
