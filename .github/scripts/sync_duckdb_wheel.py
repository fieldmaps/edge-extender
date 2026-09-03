#!/usr/bin/env python3
"""Rewrite the `duckdb` resource block in a Homebrew formula to point at the
prebuilt macOS universal2 wheel for whichever duckdb version `brew
bump-formula-pr` most recently pinned as the sdist resource, instead of the
sdist tarball (which requires compiling duckdb's C++ core with cmake/ninja).

Usage: sync_duckdb_wheel.py <path-to-formula.rb>

Exits non-zero (leaving the file untouched) if:
  - no `resource "duckdb" do ... end` block is found,
  - a duckdb version can't be parsed out of it,
  - PyPI has no cp314 macosx universal2 wheel for that exact version.

A non-zero exit is intentional and fails the CI job: it leaves the tap's
formula-bump PR open and unmerged for a human to look at, rather than
silently merging a formula that can't build (see homebrew-tap.yml, where the
subsequent "Merge Homebrew formula bump PR" step only runs on success).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

# Keep in sync with the formula's `depends_on "python@3.14"`.
PYTHON_TAG = "cp314"

RESOURCE_RE = re.compile(r'(  resource "duckdb" do\n)(.*?\n)(  end\n)', re.DOTALL)
VERSION_RE = re.compile(r"duckdb-([0-9][\w.]*)\.tar\.gz")


def fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: sync_duckdb_wheel.py <path-to-formula.rb>")

    formula_path = sys.argv[1]
    with open(formula_path, encoding="utf-8") as f:
        contents = f.read()

    match = RESOURCE_RE.search(contents)
    if not match:
        fail('could not find a `resource "duckdb" do ... end` block in the formula')

    block_body = match.group(2)
    version_match = VERSION_RE.search(block_body)
    if not version_match:
        fail(
            f"could not parse a duckdb version out of the resource block:\n{block_body}"
        )
    version = version_match.group(1)
    print(f"duckdb version pinned by brew bump-formula-pr: {version}")

    api_url = f"https://pypi.org/pypi/duckdb/{version}/json"
    with urllib.request.urlopen(api_url, timeout=30) as response:
        data = json.load(response)

    wheel_re = re.compile(
        rf"^duckdb-{re.escape(version)}-{PYTHON_TAG}-{PYTHON_TAG}-macosx_[0-9_]+_universal2\.whl$"
    )
    candidates = [
        entry
        for entry in data.get("urls", [])
        if entry.get("packagetype") == "bdist_wheel"
        and wheel_re.match(entry.get("filename", ""))
    ]
    if not candidates:
        fail(
            f"no {PYTHON_TAG} macOS universal2 wheel found for duckdb=={version} on PyPI. "
            "PyPI's duckdb wheel matrix may have changed shape (e.g. split arm64/x86_64 "
            "wheels instead of universal2); this script needs a human to update it. "
            "Leaving the sdist resource block in place -- `brew install` will now fail "
            "closed (no cmake/ninja) until this is fixed."
        )
    if len(candidates) > 1:
        fail(
            f"multiple matching wheels found for duckdb=={version}, refusing to guess: {candidates}"
        )

    wheel = candidates[0]
    wheel_url = wheel["url"]
    wheel_sha256 = wheel["digests"]["sha256"]
    print(f"resolved wheel: {wheel_url}")

    new_block = f'  resource "duckdb" do\n    url "{wheel_url}"\n    sha256 "{wheel_sha256}"\n  end\n'
    new_contents = contents[: match.start()] + new_block + contents[match.end() :]

    if new_contents == contents:
        fail("rewrite produced no change; refusing to no-op silently")

    with open(formula_path, "w", encoding="utf-8") as f:
        f.write(new_contents)

    print(
        f"Patched {formula_path}: duckdb resource now points at the {PYTHON_TAG} universal2 wheel."
    )


if __name__ == "__main__":
    main()
