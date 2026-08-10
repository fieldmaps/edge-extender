# 0028: extract `detect` out of `clean`

## Status

Accepted.

## Context

`clean`'s pipeline bundled two conceptually separate jobs into one tool:
detecting gap/overlap defects (`core/clean/_02_issues.py`) and fixing them
(`core/clean/_03_clean.py`). This mirrored the situation `match` was in
before `assign`/`clip`/`stitch` were extracted as standalone, independently
usable primitives (see `docs/explanation/assign.md`, `docs/explanation/
clip.md`, `docs/explanation/stitch.md`).

Two concrete reasons pushed this from "could split" to "should split":
detection is expensive on its own, ~17 minutes (1028-1032s, measured
twice) for `_02_issues`'s gap-union + overlap self-join on a 56,550-row,
111-country combined test file, independent of and before the actual
`ST_CoverageClean` fix pass; and it's useful standalone, inspecting a
layer's defects without committing to fixing them is a real workflow on
its own, not just a means to `clean`'s end.

## Decision

New standalone tool `detect`, with its own `core/detect/` package,
`api/detect.py`, and `topo-tools detect` CLI subcommand. `core/clean/
_02_issues.py` moved verbatim to `core/detect/_02_issues.py` (only its
`_units` import path changed). `core/clean/_units.py` was promoted to a
top-level `core/units.py` leaf module (alongside `core/constants.py`,
`core/coverage.py`, `core/io.py`, `core/duckdb_utils.py`), since both
`core/detect` and `core/clean` need its `m2_per_deg2_factor` conversion
and neither may depend on the other's package.

`clean` keeps its own `_01_inputs.py`, but its `"issues"` pipeline step
now calls `core.detect._02_issues.main()` directly instead of owning the
logic, the same pattern `core.match`/`core.mosaic` already use for
`core.assign`/`core.clip`/`core.stitch`'s stage functions, and `core.match`/
`core.change` use for `core.extend`'s. Two new import-linter leaf
contracts (`core-detect-is-leaf`, `core-units-is-leaf`) mirror the
existing `core-assign-is-leaf`/`core-clip-is-leaf`/`core-stitch-is-leaf`
trio: `core.detect`/`core.units` must never import back into any of the
five tool packages, but `clean` may freely import `core.detect`, the same
asymmetry that already lets `match`/`mosaic` import `assign`/`clip`/
`stitch` with no explicit "may depend on" contract required.

`clean`'s own external contract is unchanged: `--step issues` still runs
the exact same code, just relocated; `clean`'s issues output additionally
gained a `fixed BOOLEAN` column (per-issue outcome of the fix, computed in
`_04_outputs.py`'s `_add_outcome_columns`, a separate ask made alongside
this extraction, not itself part of the split) but that's an addition to
`clean`'s own output schema, not a consequence of moving detection out.
`detect`'s own issues schema never carries `fixed`/`filled_area_m2`/
`*_area_change_m2`; nothing was fixed when nothing was attempted.

## Consequences

`topo-tools detect example.geojson` is now a real, independently
documented CLI tool (`docs/reference/detect.md`, `docs/explanation/
detect.md`), unlike `assign`, which stayed internal-only with no CLI: the
whole point here was running detection on its own from the command line.
`clean`'s own docs (`docs/reference/clean.md`, `docs/explanation/clean.md`)
now point at `detect`'s for the detection-specific rules and history
(skipping overlap detection when valid, the bbox-inline-recompute-in-join
fix, sliver detection's removal, portolan-scale profiling) rather than
duplicating them.
