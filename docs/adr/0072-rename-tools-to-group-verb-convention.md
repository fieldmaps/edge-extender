# 0072: Rename tools to a `{group}-{verb}` naming convention

## Status

Accepted.

## Context

The package started with single-verb tool names (`extend`, `clip`, `match`,
`clean`, `map`, ...). As the tool count grew past ten, several unrelated
tools ended up sharing a verb-shaped name with no indication of which part
of the pipeline they belong to, and no room to add closely related tools
without further name collisions.

A composite-grouping convention has taken hold instead: tools cluster into
named groups, each contributing a `{group}-{verb}` CLI command. Three groups
exist now:

- `edge`: boundary-geometry tools (`edge-extend`, `edge-clip`,
  `edge-stitch`, `edge-match`, `edge-mosaic`)
- `topo`: coverage-defect tools (`topo-detect`, `topo-clean`)
- `schema`: column-crosswalk tools (`schema-map`, `schema-refactor`,
  `schema-crosswalk`)

`dissolve` and `change` stay bare, unprefixed. Both have a future group in
mind (`package` for `dissolve`, something like `recode` for `change`), but
neither group exists yet, so there's nothing to prefix them with today.

ADRs are immutable and are never rewritten or renamed once accepted. Rather
than touch the 71 existing ADR files (many of which name tools by their old
names in explaining a still-current design decision), this ADR records the
full old to new name mapping as a standalone reference. A reader following a
link from an old ADR to, say, "`clean`'s issue detection" can consult this
table to resolve it to `topo-clean`.

## Decision

Rename every tool below, at every layer: CLI command name, Python module/
package name (`topo_tools/core/{name}/`, `topo_tools/api/{name}.py`), test
file name, docs file names (`docs/reference/`, `docs/explanation/`,
`docs/tutorials/`), and the tool's own table-naming disambiguation suffix
(e.g. `{input}_edge_match`).

| old name | new CLI command | new module/dir name | group |
| --- | --- | --- | --- |
| `extend` | `edge-extend` | `edge_extend` | edge |
| `clip` | `edge-clip` | `edge_clip` | edge |
| `stitch` | `edge-stitch` | `edge_stitch` | edge |
| `match` | `edge-match` | `edge_match` | edge |
| `mosaic` | `edge-mosaic` | `edge_mosaic` | edge |
| `detect` | `topo-detect` | `topo_detect` | topo |
| `clean` | `topo-clean` | `topo_clean` | topo |
| `map` | `schema-map` | `schema_map` | schema |
| `refactor` | `schema-refactor` | `schema_refactor` | schema |
| `crosswalk` | `schema-crosswalk` | `schema_crosswalk` | schema |
| `dissolve` | `dissolve` (unchanged) | `dissolve` (unchanged) | standalone |
| `change` | `change` (unchanged) | `change` (unchanged) | standalone |

`topo_tools/core/assign/` has no CLI or `api.*()` of its own (it's a shared
primitive called from other tools' `api.*()` layers) and is unaffected.

Internal pipeline `--step` tokens (e.g. `schema-map`'s literal `"map"` stage
choice, `schema-crosswalk`'s `"map"`/`"apply"` choices) are stage names
scoped to one tool's own pipeline, not tool names, and are unaffected by
this rename.

## Consequences

Every tool's identity is now legible from its name alone: which group it
belongs to, and (via the group) roughly what kind of problem it solves.
Adding a new tool to an existing group no longer risks colliding with an
unrelated tool's verb.

Every internal cross-reference between tools (docstrings, `CLAUDE.md`'s Key
Patterns bullets, import-linter contract `id`/`name` strings, table-naming
collision-avoidance comments) had to be updated in the same pass to stay
consistent; a partial rename would have left the codebase self-contradictory
about which name is current.

ADR files 0001 through 0071 still refer to tools by their pre-rename names
and are not updated. This is a deliberate one-time cost: consulting this
table resolves any old name in that history to its current one, and it's
cheaper than perpetually renaming immutable records or accepting an
ever-growing rename backlog against them.
