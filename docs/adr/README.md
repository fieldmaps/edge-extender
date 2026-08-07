# docs/adr/

Architecture Decision Records: one immutable file per past investigation or
decision, using Michael Nygard's minimal headers (Title, Status, Context,
Decision, Consequences).

`docs/adr/` states *why* a specific decision was made, once, and is never
rewritten afterward. A reversed decision gets a new ADR whose Status reads
`Superseded by ADR-00NN`; the old file stays as-is. This is what
distinguishes it from `docs/explanation/`, which documents current rationale
and is squashed/rewritten as understanding evolves.

Numbered `NNNN-title.md`, sequential, never reused. A bullet belongs here
instead of `CLAUDE.md`'s "Key Patterns" or a `docs/explanation/*.md` file if
it would otherwise be a paragraph starting with "confirmed", "previously",
"was misdiagnosed", or "empirically tested" — narrative investigation
history, not current-state description.
