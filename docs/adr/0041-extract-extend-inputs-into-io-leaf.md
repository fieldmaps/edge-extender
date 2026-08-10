# 0041: extract `extend`'s `_01_inputs` load-and-clean step into `core.io`

## Status

Accepted.

## Context

`extend/_01_inputs.py` was 8 lines, and every line already delegated to
leaf modules: `core.io.read_and_reproject` for the read/reproject, and
`core.coverage.has_valid_topology`/`coverage_clean` for a zero-tolerance
(`gap_maximum_width=0`) cleanup pass. It contained no Voronoi-specific
logic. It lived inside `core/extend/` only because `extend` needed it
first; `match/_01_inputs.py` and `change/_01_inputs.py` later reached
across the tool-package boundary for the same utility
(`from topo_tools.core.extend import _01_inputs as extend_inputs`) rather
than it being a leaf from day one.

This is the same shape of problem `docs/adr/0028` already fixed once:
genuinely tool-neutral logic stranded inside the first tool that needed
it, reused cross-tool via a direct package import instead of a leaf.

## Decision

Moved the load-and-clean logic into `topo_tools/core/io.py` as
`read_reproject_and_clean(conn, name, path)`, composing the existing
`read_and_reproject` with `has_valid_topology`/`coverage_clean` (imported
from `.coverage`; leaf-to-leaf, no circularity, `core/coverage.py` only
imports `core.constants`/`core.units`). Behavior is unchanged: same
`gap_maximum_width=0` check, same `{name}_01` table.

`extend/_01_inputs.py` keeps its module, per the numbered-stage
convention every tool follows, but its `main()` is now a one-line
delegation to `io.read_reproject_and_clean()`, the same shape ADR-0028
left `clean/_01_inputs.py` in. `match/_01_inputs.py` and
`change/_01_inputs.py` both now import `read_reproject_and_clean` from
`core.io` instead of aliasing `core.extend._01_inputs`.

This removes `change`'s only remaining dependency on `core.extend`
entirely, so the one-way `change-may-use-extend-not-reverse`
import-linter contract is replaced with `change-independent-of-extend`
(type `independence`), mirroring the existing
`mosaic-independent-of-extend` contract. `match` keeps its `core.extend`
dependency via `_02_groups.py`'s reuse of `_02_lines`/`_05_merge`/
`attempt`, the actual Voronoi algorithm reused as a subroutine (the same
pattern `mosaic` uses for `clip`/`stitch`'s stage functions), which is
out of scope here: `match-may-use-extend-not-reverse` is untouched.

## Consequences

`core.change` no longer imports `core.extend` anywhere; `docs/reference/
shared.md`'s "change MAY reuse extend's logic" bullet is removed, and
`docs/explanation/match.md`/`change.md`'s `_01_inputs` stage descriptions
now point at the shared `core.io.read_reproject_and_clean()` helper
instead of "extend's own loader." No test changes were needed:
`tests/test_extend.py::test_inputs_closes_noise_scale_gap` calls
`extend._01_inputs.main()` directly and passes unchanged, since its
behavior is identical, just relocated.
