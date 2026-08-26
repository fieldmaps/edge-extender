# Multi-platform distribution prep

Local prep for `topo-tools`' pipx/uv (done, README already updated),
conda-forge, Homebrew, and winget channels. See
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
binary wheels for declared resources, so this is expected). Less expected:
`topo-tools`' own build backend, `uv_build`, is itself a Rust/maturin
package, so Homebrew building it from its declared resource needs
`depends_on "rust" => :build` too, else the nested `maturin` build fails.
(A wheel-based main `url`, skipping `uv_build` entirely, looked like a
cleaner fix and was tried first, but Homebrew's pip helper unpacks any `url`
as a source tree and forces `--no-binary`, so it always tries to rebuild a
wheel's contents as if they were an sdist and fails; the `rust` dependency
is the one that actually works.) `pyyaml` additionally needed `depends_on
"libyaml"` per `brew audit`. Resource names must match Homebrew's PyPI-name
normalization (`uv-build`, not `uv_build`), and the main `url` must be the
long `files.pythonhosted.org` hash-path form, not the short `/packages/
source/...` form conda-forge prefers, `brew audit --strict` catches both if
missed.

If the extra Rust toolchain dependency is worth avoiding, the actual fix
would be switching `topo-tools`' own build backend from `uv_build` to a
pure-Python one (`hatchling`/`flit-core`), which removes this class of
problem from every packaging channel, not just Homebrew, worth considering
separately rather than folded into this prep.

Next steps: cut 0.5.3, update the formula's `url`/`sha256`, create
`OCHA-DAP/homebrew-topo-tools`, push `Formula/topo-tools.rb` there. Install
command for users: `brew install OCHA-DAP/topo-tools/topo-tools` (Homebrew
≥6.0.0's tap trust auto-trusts a fully-qualified install, no separate `brew
tap`/`brew trust` step needed).

## winget (`packaging/winget/`)

`entrypoint.py` + `topo-tools.spec`: a verified PyInstaller `--onedir` build
(not `--onefile`, see the plan for why). Spiked locally on macOS (can't
cross-build a Windows exe from here): `pyinstaller-hooks-contrib` ships a
`hook-duckdb.py` already, no custom hook needed. The frozen bundle ran a
real `topo-detect` command against `tests/fixtures/edge_stitch_coincident_
boundary.parquet` and produced correct output, so `duckdb` and its spatial
extension both load correctly from inside the bundle.

`build-windows-exe.yml`: a draft CI job (`windows-latest`, needed since
PyInstaller doesn't cross-compile) that repeats this build in CI and zips
the result. Not wired into `.github/workflows/publish.yml` yet, review and
paste it in alongside the existing `build`/`publish` jobs.

Next steps: wire the job in, add a release-asset upload step, then submit
the initial manifest to `microsoft/winget-pkgs` via `wingetcreate`, and add
a `wingetcreate update` step to automate future version bumps.
