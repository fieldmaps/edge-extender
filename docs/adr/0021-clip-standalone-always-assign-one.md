# 0021: Standalone clip always assigns via assign-one, never expects parent_fid

## Status

Accepted.

## Context

`clip`'s original standalone contract required its children input to
already carry a `parent_fid` column, raising `ValueError` otherwise. That
requirement was ported unmodified from `match`/`mosaic`'s internal
plumbing, where a prior assign stage genuinely does hand `clip` an
already-tagged table, not a deliberate constraint for a standalone,
user-facing tool. In practice it meant `clip` could never be used on its
own against a raw children file and a raw parent file, the single most
common ad hoc use (e.g. clip one already-extended per-country layer
against a new parent/clip file), without first routing through `mosaic` or
hand-rolling an assign step.

## Decision

Standalone `clip` (`api.clip.clip()` / CLI `clip`) no longer requires or
reads a pre-existing `parent_fid` column. It always performs its own
internal assignment via assign-one's per-file majority-vote strategy (see
`docs/explanation/assign.md`, ADR-0019) between loading its inputs and
clipping. There is no `--assign-strategy` flag and no auto-detection:
standalone `clip` is unconditionally an assign-one operation, since a
single input file is exactly assign-one's natural unit (one file, one
shared parent). `assign-many`'s per-child-plurality granularity remains a
separate, unrelated crosswalk-building concern that standalone `clip` no
longer serves.

The low-level `core.clip._03_clip.main()` mechanism (the per-`parent_fid`
subprocess clip itself) is untouched and keeps its own "table_in MUST
already carry parent_fid" contract; `match`/`mosaic` keep calling it
directly with their own already-tagged tables.

## Consequences

A children file whose rows genuinely belong to more than one parent within
the same file (the old "already-assigned crosswalk" input mode) can no
longer be fed to standalone `clip` directly: assign-one forces every child
in one file onto one shared parent, silently dropping any child that
doesn't agree, per ADR-0019's residual risk (a file too small to form a
real majority, or a genuine tie, falls back to parent id rather than a
geometric signal).
