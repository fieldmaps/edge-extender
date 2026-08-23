# 0067: `map` assigns each chain column's role independently, never via a sibling

## Status

Accepted. Refines ADR-0066's role-assignment step (that ADR stays as the
historical record of the earlier wording; it is not edited).

## Context

Testing `map` against real Angolan and Mozambican COD-AB source files
surfaced two failures in `_assign_chain_roles()`'s `elif any_embeds: role
= "name"` default, which assigns `name` to any non-embedding column in a
chain group as soon as *some other* column in that same group embeds the
resolved parent.

Angola's `Provincia_2025.shp` has four count-21 companions at admin1:
`Cod_Alfa_N` (`"AOUGE03"`) embeds the country code `"AO"`, so it resolves
`code`; `Cod_Prov` (`"12"`), `Cod_Alfa_P` (`"UGE"`), and `Nome_Prov`
(`"Uíge"`) don't embed anything, so all three defaulted to `name` even
though `Cod_Prov` is plainly a second, non-compound numeric province code
(digit-shaped, per `_looks_code_shaped()`). The same province's
`admin2`-level file, which lacks `Cod_Alfa_N`, has no column embedding at
all, so its otherwise-identical `Cod_Prov` fell through to the individual
shape fallback and correctly resolved `code`, an inconsistency purely
because of which sibling happened to be present.

Mozambique's `moz_admin3`/`moz_admin4` surfaced a more serious case:
`area_sqkm` (a per-feature area in km²) happens to be row-unique at the
same cardinality as `adm3_pcode`/`adm4_pcode`, so it clusters into that
level's chain group. It doesn't embed the parent, but `adm3_pcode` does,
so `area_sqkm` defaulted to `name` and claimed the bare `adm3_name`
target. The file's actual `adm3_name` column fails the file-wide
bijection test in step 1 (Mozambique's district names legitimately
repeat under different provinces), so it never enters the chain group at
all; it instead reaches the bracket step, where it passes the function
check but finds the level's `name` role already claimed by `area_sqkm`,
so it resolves to `supplemental` instead of `name`. The real name column
is displaced by a numeric area column with no name-shaped evidence at
all.

Both failures share a cause: role assignment let one column's embedding
result decide another column's role, instead of testing each column on
its own evidence.

## Decision

`_assign_chain_roles()` MUST assign each chain-level column's role from
its own evidence only: `code` if it embeds the level's resolved parent,
or (independently) if it passes `_looks_code_shaped()`; `name` otherwise.
No column's role depends on whether a different column in the same group
embedded the parent.

## Consequences

`Cod_Prov` resolves `code` in both Angola files regardless of which
sibling is present. `area_sqkm` resolves `code` (shape-fallback,
containing digits) instead of `name`, freeing Mozambique's real
`adm3_name`/`adm4_name` to resolve `name` directly instead of
`supplemental`. `_looks_code_shaped()`'s existing false-positive risk (a
digit-containing name, or an alpha-only code with no digits at all, like
Angola's `Cod_Alfa_P`) is unchanged and still accepted per ADR-0066; this
change only removes the additional, unjustified risk of one column's
embedding silently overriding a same-level sibling's own evidence.
