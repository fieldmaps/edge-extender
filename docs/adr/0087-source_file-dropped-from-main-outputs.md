# 0087: `source_file` dropped from main outputs, shortened in issues reports

## Status

Accepted.

## Context

`source_file` is tagged onto every child row at load time
(`core.assign.load_children`'s `'{path}' AS source_file`, and
`core.edge_match._01_inputs.load_and_clean_child`'s `ALTER TABLE ... ADD
COLUMN source_file`), purely so `assign_one()` can group a file's children
for its per-file majority-vote assignment (`core/assign/_one.py`, `GROUP
BY c.source_file, pr.parent_fid`). It was never meant to be user-facing:
its presence in `edge-mosaic`/`edge-match`'s exported main output was an
oversight that made its way into the documented behavior contract
(`docs/reference/edge_mosaic.md`, `docs/reference/edge_match.md`) without
being a deliberate design choice.

Standalone `edge-clip`'s `core/edge_clip/_02_outputs.py` already excludes
`source_file` from both its main and issues exports
(`SELECT * EXCLUDE (source_file)`), the correct end state this decision
brings `edge-mosaic`/`edge-match`/`edge-stitch` in line with, for the main
output at least.

A bare filename alone in the issues report loses information when two
input files in different directories share a name (e.g. two countries
each holding their own `adm2.parquet`), so the issues report keeps
`source_file` but shortens it to parent-directory-plus-filename rather
than dropping it or keeping the full path.

## Decision

- The main combined/geometry output (the mosaicked/matched/stitched file)
  MUST NOT carry a `source_file` column, for `edge-mosaic`, `edge-match`,
  and standalone `edge-stitch`. Each tool's outputs stage exports through
  a `SELECT * EXCLUDE (source_file)` view rather than the raw table.
  `edge-stitch`'s main output only excludes the column conditionally,
  since a standalone `edge-stitch` run's input isn't guaranteed to carry
  one at all.
- `edge-mosaic`/`edge-match`'s issues report keeps `source_file` for any
  row kind that has one, but shortened via
  `array_to_string(list_slice(str_split(source_file, '/'), -2, -1), '/')`
  to its parent directory plus filename, never the full input path.
  `edge-stitch`'s issues rows are gap-only and were already always null
  here, so there's nothing to shorten.
- `topo-clean`, standalone `edge-clip`, and `dissolve` are unchanged:
  `topo-clean` keeps its always-null `source_file` column (a single-layer
  tool has no per-child origin file); `edge-clip` already matched this
  decision's end state before it existed.
- The internal `source_file` column (on `{name}_child_01`,
  `{name}_02_assign`, and the pre-export main table) is unchanged: it
  stays a full path, since `assign_one`'s per-file grouping needs it to
  uniquely identify a file across directories.

## Consequences

Any existing downstream consumer reading `source_file` off a combined
`edge-mosaic`/`edge-match`/`edge-stitch` output file will need to stop;
that column no longer exists there. Issues reports remain traceable to an
input file by name, just not by full path; two files sharing both a
filename and their immediate parent directory name (e.g. reused across
unrelated deeper subtrees) would still collide in the shortened label,
an accepted, documented limitation since the internal grouping column
that assignment correctness depends on is unaffected. `--debug` mode
still exposes the full-path `source_file` column on each tool's
pre-export internal table (`{name}_04` for `edge-mosaic`, `{name}_05` for
`edge-match`) for deeper investigation, e.g. tracing a cross-provenance
seam disagreement.
