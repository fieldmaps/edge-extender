# Multi-platform distribution prep

Local prep for `topo-tools`' pipx/uv (done, README already updated),
conda-forge, and Homebrew channels. See
`/Users/computer/.claude/plans/can-you-look-into-generic-puppy.md` for the
full plan this implements.

## Prerequisite: cut a 0.5.3 release first

`pyproject.toml` now has `license-files = ["LICENSE"]` (previously missing,
so `uv build`'s sdist didn't include `LICENSE` at all: verified by building
it, then trying to build the conda-forge recipe against it, which failed
with "No license files were copied"). `CHANGELOG.md` has an `[Unreleased]`
entry for this. Both the conda-forge recipe and the Homebrew formula below
reference the current PyPI release (0.5.2), which is missing the license
file (PyPI uploads are immutable, this can't be fixed on 0.5.2 itself).

Before submitting either: cut the 0.5.3 release per
`docs/how-to/publishing.md`, then update `packaging/conda-forge/recipe.yaml`'s
`context.version`/`source.sha256` and `packaging/homebrew/topo-tools.rb`'s
`url`/`sha256` to match the new sdist/wheel.

## conda-forge (`packaging/conda-forge/recipe.yaml`)

v1 format, generated with `grayskull pypi --use-v1-format --strict-conda-forge`,
then hand-fixed (`license_file`, `repository`/`documentation`, dropped a
redundant `python_min` override) and cleanly linted with `conda-smithy
recipe-lint --conda-forge`. Built and tested end-to-end locally with
`rattler-build` against a LICENSE-fixed sdist (standing in for the real
0.5.3): install and `topo-tools --help` both passed.

Next steps: cut 0.5.3, update the recipe's version/sha256, open a PR against
`conda-forge/staged-recipes` with this file under `recipes/topo-tools/`.

## Homebrew (`packaging/homebrew/topo-tools.rb`)

`Language::Python::Virtualenv` + `virtualenv_install_with_resources`, the
standard pattern. Built, `brew audit --strict`-clean, installed, and manually
re-verified (`topo-tools --version` plus a real `topo-detect` run against a
test fixture) end-to-end via a scratch tap, not pushed anywhere; the scratch
tap and its test install are already cleaned up from this machine.

`duckdb`'s sdist compiles from source, needing `depends_on "cmake" =>
:build` and `depends_on "ninja" => :build` (Homebrew's pip helper disables
binary wheels for declared resources, so this is expected). `topo-tools`'
own build backend is `hatchling` (pure Python), declared as `resource
"hatchling"`, so no Rust toolchain dependency is needed. `pyyaml`
additionally needed `depends_on "libyaml"` per `brew audit`. Resource names
must match Homebrew's PyPI-name normalization, and the main `url` must be
the long `files.pythonhosted.org` hash-path form, not the short `/packages/
source/...` form conda-forge prefers, `brew audit --strict` catches both if
missed. (A wheel-based main `url` looks like a cleaner way to skip building
the sdist entirely, but doesn't work: Homebrew's pip helper unpacks any
`url` as a source tree and forces `--no-binary`, so it always tries to
rebuild a wheel's contents as if they were an sdist and fails.)

Live on `OCHA-DAP/homebrew-topo-tools`. Install command for users: `brew
install OCHA-DAP/topo-tools/topo-tools` (Homebrew ≥6.0.0's tap trust
auto-trusts a fully-qualified install, no separate `brew tap`/`brew trust`
step needed).

Version bumps are automated: `.github/workflows/publish.yml`'s
`update-homebrew-tap` job runs `brew bump-formula-pr` after each PyPI
publish, opening a PR against the tap with the new `url`/`sha256` and
regenerated resource blocks (review and merge like any other PR, nothing
merges unattended). That job needs a `HOMEBREW_TAP_TOKEN` repository secret
(a fine-grained PAT scoped to `OCHA-DAP/homebrew-topo-tools` with
`Contents: Read and write` and `Pull requests: Read and write`), set up
once by a repo admin.
