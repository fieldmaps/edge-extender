# shared

See `specs/README.md` for the MUST/SHOULD/MAY convention. Rules here apply
across more than one tool; a tool's own file references this one by name
instead of repeating them.

## Import boundaries (mechanically enforced)

- Core tool logic MUST NOT depend on the command-line interface.
- The public API layer MUST NOT depend on the command-line interface.
- The `match` tool MAY reuse `extend`'s logic; `extend` MUST NOT depend on
  `match`.
- The `change` tool MAY reuse `extend`'s logic; `extend` MUST NOT depend on
  `change`.
- The shared constants, coverage-validation, file I/O, and
  database-connection helpers MUST NOT depend on any of the four tools --
  they are leaf building blocks usable by all of them.

## Coverage-topology checks

- The shared overlap/mismatched-edge check MUST NOT be treated as a gap
  check: it reports "no violations" both when a real, fully-enclosed gap
  exists with no overlaps, and when the data has collapsed to nothing.
- The shared gap check MUST detect fully-enclosed interior holes only, in
  the union of a layer's geometries.

## Hard gates at each tool's output stage

- `extend` and `match` MUST raise if their final output has any overlap or
  any gap.
- `clean` MUST raise if its final output has any overlap. It MUST NOT raise
  over an unfilled gap -- gaps may legitimately remain by design and are
  only logged.
- `change` performs no topology hard gate at all; it is a read-only
  comparison between two inputs, not a fix.
