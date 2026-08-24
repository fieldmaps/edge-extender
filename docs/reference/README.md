# docs/reference/

Plain-English, verifiable behavior contracts for each tool, using RFC 2119
keywords:

- **MUST** / **MUST NOT**: required; a violation is a bug.
- **SHOULD** / **SHOULD NOT**: expected default behavior.
- **MAY**: explicitly allowed, not required.

`docs/reference/` states *what* each tool currently does, verified directly
against source. It does not explain *why* (rationale, rejected alternatives,
and benchmark data live in `docs/explanation/`). Tests enforce a subset of
these contracts; reference docs are not a substitute for tests, and a code
change must keep both in sync.

One file per tool (`topo_clean.md`, ...). A rule identical across more than one
tool goes in `shared.md`, referenced by name instead of repeated in each
tool's file.
