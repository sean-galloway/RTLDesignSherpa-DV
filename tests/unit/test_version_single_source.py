# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
"""The version must have exactly ONE source, and nothing used to enforce that.

This package carried the version in two unlinked places -- `[project] version` in
pyproject.toml and `__version__` in src/CocoTBFramework/__init__.py -- and they
drifted for six releases. The published 0.6.7 wheel shipped
`__version__ = "0.6.1"` while its own METADATA said `Version: 0.6.7`, so anything
asking the package its own version got an answer three releases stale.

That is not cosmetic. `CocoTBFramework.__version__` is the natural thing to check
after an upgrade -- it is what a consuming session reaches for to confirm a
reinstall took effect -- and it was silently wrong, so every verification built on
it passed or failed for the wrong reason.

Fixed by making the packaging metadata READ the module literal
(`[tool.setuptools.dynamic] version = {attr = ...}`), which makes the literal the
single source. This test exists because that arrangement is easy to undo by
accident: re-adding `version = "x.y.z"` to `[project]` looks harmless and
resurrects the drift.

Deliberately text assertions rather than TOML parsing: the CI matrix includes
Python 3.10, where `tomllib` does not exist and `tomli` is only in the `sim`
extra, so parsing would make this fragile for no gain.

tooling TASK-021.
"""

from __future__ import annotations

import importlib.metadata as md
import re
from pathlib import Path

import pytest

import CocoTBFramework

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
DIST = "cocotb-framework"


def _project_block(text: str) -> str:
    """Just the [project] table, so a `version =` elsewhere is not a false hit.

    `[tool.ruff]` carries `target-version`, and `[tool.setuptools.dynamic]` must
    carry a `version =` -- neither is the literal this test is looking for.
    """
    start = text.index("[project]")
    nxt = re.search(r"^\[(?!project\])", text[start + 1 :], re.M)
    return text[start : start + 1 + nxt.start()] if nxt else text[start:]


def test_project_declares_version_dynamic():
    text = PYPROJECT.read_text()
    assert 'dynamic = ["version"]' in text, (
        "[project] must declare dynamic = [\"version\"] so the version comes from "
        "the module literal. tooling TASK-021."
    )


def test_project_has_no_literal_version():
    """The regression this test exists for: a literal creeping back in."""
    block = _project_block(PYPROJECT.read_text())
    literal = re.search(r'^version\s*=\s*["\']', block, re.M)
    assert literal is None, (
        "[project] has a literal `version = ...` again. With the module literal "
        "as well, the two WILL drift -- they did for six releases, and the "
        "published 0.6.7 wheel self-reported 0.6.1. Remove the literal here and "
        "let [tool.setuptools.dynamic] read CocoTBFramework.__version__."
    )


def test_dynamic_points_at_the_module_literal():
    text = PYPROJECT.read_text()
    assert "[tool.setuptools.dynamic]" in text, "missing [tool.setuptools.dynamic]"
    assert 'version = {attr = "CocoTBFramework.__version__"}' in text, (
        "[tool.setuptools.dynamic] must read the version from "
        "CocoTBFramework.__version__ -- that literal is the single source."
    )


def test_module_version_is_a_sane_literal():
    v = CocoTBFramework.__version__
    assert isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+([.\-+].*)?", v), (
        f"__version__ is {v!r}; expected a release-shaped version string"
    )


def test_installed_metadata_matches_the_module():
    """The end-to-end check: what pip reports IS what the module reports.

    Skipped when the installed distribution is not this source tree -- comparing
    against an unrelated wheel in some other venv would be noise, not a finding.
    CI installs with `pip install -e .`, so this runs there.
    """
    try:
        dist = md.distribution(DIST)
    except md.PackageNotFoundError:
        pytest.skip(f"{DIST} is not installed in this environment")

    installed_from_here = False
    try:
        direct = dist.read_text("direct_url.json") or ""
        installed_from_here = str(REPO_ROOT) in direct
    except Exception:
        pass
    if not installed_from_here:
        pytest.skip(
            f"installed {DIST} is not this tree (no direct_url pointing at "
            f"{REPO_ROOT}); nothing to compare"
        )

    assert dist.version == CocoTBFramework.__version__, (
        f"pip reports {dist.version!r} but CocoTBFramework.__version__ is "
        f"{CocoTBFramework.__version__!r}. The single-source arrangement is "
        "broken -- this is exactly the drift that shipped in 0.6.7."
    )
