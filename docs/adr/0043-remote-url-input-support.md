# 0043: accept `http(s)://` URLs as read-role file arguments

## Status

Accepted.

## Context

Every read-role file argument (children, parent/clip, old/new) was
`Path()`-wrapped twice: once in `cli/main.py` before calling the matching
`api.*()` function, and again inside that `api.*()` function itself.
`pathlib.Path` only preserves a double leading slash at the very start of
an absolute path (POSIX's 2-slash convention); a `//` appearing mid-string
collapses to one, so `Path("https://data.source.coop/x")` silently becomes
`PosixPath('https:/data.source.coop/x')`. Passing a real `https://` URL as
`INPUT_FILE` therefore failed with `duckdb.IOException: No files found
that match the pattern "https:/..."`, even though DuckDB itself reads
remote Parquet over HTTP natively (`read_parquet('https://...')` from a
bare `duckdb` CLI session works today, no extension setup needed).

Every tool's actual file read already funnels through `core/io.py`'s
`read_and_reproject`/`read_reproject_and_clean` (consolidated by
docs/adr/0041), so the read side had exactly one place to fix. The harder
part was naming: each `api.*()` also derives its default output filename
from the input's stem (`input_path.with_stem(input_path.stem + "_extended")`)
and its internal DuckDB table name from the input's basename
(`input_path.name.replace(".", "_")`, used as a literal `.duckdb`/`.log`
filename in `core/duckdb_utils.py`) — neither works on a raw URL string.

## Decision

Added three helpers to `topo_tools/core/io.py`:

- `resolve_input_path(path)`: returns the original string unchanged if it
  starts with `http://`/`https://`, otherwise `Path(path)`. The only place
  a read-role argument is converted now, in both `cli/main.py` (which
  previously double-converted) and every `api/*.py`.
- `input_basename(path)`: `path.name` for a `Path`; for a URL,
  `Path(urlparse(path).path).name`. Drives default-output-naming and
  internal table-name derivation for both local and remote inputs.
- `default_output_path(input_path, suffix)`: same directory as
  `input_path` (current working directory if `input_path` is remote),
  basename stem + `suffix`. Reproduces today's local-file behavior
  byte-for-byte; only the remote case is new.

`read_and_reproject`/`read_reproject_and_clean` widened their `path: Path`
type hint to `Path | str` and swapped the `path.suffix` parquet check for
`Path(input_basename(path)).suffix` (a bare `str` has no `.suffix`). The
read expression itself needed no change: it already interpolates whatever
string it's given, and `resolve_input_path` guarantees a URL now arrives
intact.

`cli/main.py` stopped `Path()`-wrapping read-role arguments entirely
(children, parent/clip, old/new, `--input`/extra-inputs), passing the raw
`str` straight through — each `api.*()` already resolves it via the new
helper, so the CLI layer's own wrap was redundant even before this bug,
just newly harmful once URLs were in scope. Output-role arguments
(`output_file`, `issues_file`, `overlay_file`) are untouched, always
local. `change`'s two-stem default output name
(`{old_stem}_{new_stem}_changelog.csv`) and `clip`'s multi-file
`dest_by_source` mapping don't fit `default_output_path`'s single-input
shape, so both keep bespoke inline logic built from `input_basename`
directly.

Only `.parquet` was verified: DuckDB reads remote Parquet over HTTP
natively, and it's the only format the portolan catalog actually serves.
The `ST_Read()` branch (non-parquet formats, GDAL-backed) was not
exercised against a remote URL.

## Consequences

Any read-role file argument across all 8 tools MAY now be an
`http://`/`https://` URL to a `.parquet` file (see
`docs/reference/shared.md`). Output-role arguments MUST still always be a
local filesystem path — no code path resolves them any other way. Verified
live against `https://data.source.coop/hdx/cod-ab/...` for all 8 CLI
commands, each producing correct output. Non-parquet remote URLs remain
unverified and are not a supported claim.
