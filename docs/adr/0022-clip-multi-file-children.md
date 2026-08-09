# 0022: Standalone clip's children role MAY span multiple files

## Status

Accepted.

## Context

Running standalone `clip` (see ADR-0021) across a catalog of per-country
children files against one shared large parent/clip file (a global admin0
layer, hundreds of MB) reloads and reprojects that parent from scratch on
every single call. That reload dominates runtime once dozens or hundreds
of children files need clipping against the same parent one call at a
time.

`mosaic` already solves the loading half of this problem: its children
role MAY span multiple files, loaded and unioned once by
`core.assign._01_inputs.main()` (which also loads the parent exactly
once), with `core.assign._02_one.main()`'s majority vote already
`PARTITION BY source_file`, computing each file's own assigned parent
independently rather than one vote across everything. The only place
`mosaic`'s existing pattern doesn't fit `clip`'s use case is output shape:
`mosaic` combines every children file into one merged output, while this
use case needs one clipped output *per* children file.

GDAL's own CLI (`gdal vector clip`/`convert`) has no precedent for
many-inputs-sharing-one-resource-to-many-separate-outputs either: `clip`/
`convert` are strictly one-in-one-out, `concat` merges many inputs into one
output (the same shape as `mosaic`), `partition` goes the opposite
direction (one input to many outputs by attribute). Batching many-to-many
is left to scripting on GDAL's side too.

Naming outputs automatically was considered and rejected: real children
files clipped this way are frequently all named identically (e.g. every
country's file in a per-country catalog literally named
`extended.parquet`, only the parent directory differing), so any
filename-derived-from-input-stem convention collides immediately.

## Decision

`clip`'s children role MAY now span multiple files, both at the API
(`api.clip.clip(children_paths, parent_path, output_paths, *, name, ...)`)
and CLI (`--input`/`--output`, each repeatable and comma-separable) layers.
`core.assign._01_inputs`/`_02_one` are reused unchanged, called directly
from `api.clip.clip()` with no per-tool wrapper, the same pattern
`api.mosaic.mosaic()` already uses for its own inputs/assign steps.

`output_paths` MUST be an explicit list the same length as
`children_paths`, paired by position; there is no auto-naming or
output-directory convention, given the filename-collision problem above.
`name` (the run's internal table/tmp-file identifier) MUST also be given
explicitly once there are multiple children files, since there is no
longer a single input path to derive one from the way the single-file case
does.

If any one children file's rows are all gone after clipping (assign-one
found no overlap for it, or every clipped result was empty), the whole
call raises `RuntimeError` naming that file **before writing any output**,
so a multi-file call either fully succeeds or writes nothing. This keeps
`clip`'s existing no-partial-continue philosophy (see
`docs/reference/clip.md`'s hard-fail-on-the-first-bad-`parent_fid` rule)
rather than adopting `mosaic`'s own per-child drop-and-issues-report model,
which `clip` has never had.

The CLI's `--input`/`--output` options add pairs beyond the first
positional `INPUT_FILE CLIP_FILE [OUTPUT_FILE]` triple, so the existing
single-file invocation is unchanged when they're omitted. The same
`--input` idiom (repeatable, comma-splittable) was also added to `mosaic`'s
CLI alongside its existing glob-pattern positional, so both tools share one
consistent way to list "more files than the positional alone."

## Consequences

A caller must build its own paired `output_paths`/`--output` list; `clip`
does no naming inference. There is still no per-file drop-and-continue or
issues-report option for `clip`, unlike `mosaic`: one empty children file
aborts the whole multi-file call. `core.clip._engine.main()` (the
per-`parent_fid` subprocess mechanism, unchanged by this decision) and its
own `match`/`mosaic` call sites are unaffected either way.
