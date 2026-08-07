# Run an at-scale test against the portolan catalog

Use the portolan catalog (see `CLAUDE.md`'s Test Datasets section for its
location and the read-only hard rule) when the two bundled fixtures
(Burundi, Chile) aren't enough -- e.g. checking a fix at real
multi-thousand-fid scale, or exercising `change` against a genuine old/new
version pair.

## Layout

STAC-like: `{iso3}/{latest,vNN}/{adm0..adm3,lines,points}/{original,
extended,matched}.parquet`. Distinct `vNN` dirs are always genuinely
different content; `latest` is whichever `vNN` is newest.

## Picking a file (`extend` / `match` / `clean`)

Any single `{iso3}/{vNN}/{adm_level}/original.parquet` works. Point every
`--output-path`/`--tmp-dir`/`--debug` export outside the catalog (the
session scratchpad or `/tmp`) -- never back into `portolan/`.

## Picking an old/new pair (`change`)

1. Browse the country's catalog (local path, or fetch `./{iso3}/catalog.json`
   from the STAC root) and list its `vNN` dirs.
2. Not every country/admin-level has 2+ versions yet -- confirm both `vNN`s
   you want to compare actually exist before running `change`.
3. Run `change` with the older version as the first argument, the newer as
   the second; point every output path outside the catalog.

`docs/explanation/change.md`'s "Portolan-scale profiling" section has real
timing/memory numbers from Philippines admin3 (`v02`->`v03`), Ethiopia
admin3 (`v01`->`v04`), and Ukraine admin3 (`v01`->`v05`) runs, plus a
`--link-by-code` footgun found on the Philippines pair.
