---
title: Packaging and the wheel boundary
summary: This package is consumed as a BUILT WHEEL, so edits are invisible until reinstall - and data files ship only if package-data says so, which a release learned the hard way.
---

# Packaging and the wheel boundary

`cocotb-framework` (import name `CocoTBFramework`) is published to PyPI and
uses a `src/` layout. Two consequences bite regularly enough to be worth
stating before anything else.

## Your edits are invisible to the main repo until you reinstall

The main repo's venv consumes this package as a **built wheel**, not as a path
reference. Editing a file here changes nothing over there until:

```bash
/mnt/data/github/RTLDesignSherpa/venv/bin/pip install --quiet /mnt/data/github/RTLDesignSherpa-DV
```

This is the single most common way to spend an hour debugging a fix that is
already correct. If a change "has no effect" in an RTL sim, reinstall before
you investigate anything else. Do it as the last step of every increment, the
same way you run the tests.

Locally, work with an editable install (`pip install -e ".[dev,all]"`) so this
repo's own tests see changes immediately — the wheel boundary is between
*repos*, not within this one.

## Data files ship only if `package-data` says so

Python packaging includes `.py` files by default and **nothing else**. Any
CSV, template, or reference table you add under `src/` is absent from the
wheel unless `pyproject.toml` lists it.

**Case study — 0.6.1.** The JEDEC timing CSVs were dropped from every wheel.
The code that loaded them was fine; the files simply were not there, so the
failure surfaced only for an installed user, never in this repo where the
source tree is present. The fix (`81f6a10`) was one `package-data` line, and
the lesson is that the local test suite structurally *cannot* catch this
class of bug.

The pattern that came out of it:

```toml
[tool.setuptools.package-data]
"CocoTBFramework.components.dfi" = ["jedec/*.csv", "jedec/*.md", "jedec/*.example"]
```

Note the `*.example` glob. A fill-in template deliberately carries a suffix
that keeps it out of auto-discovery (the DFI unit suite load-tests every
`*.csv` in that directory, and a template full of `FILL_ME` would fail), and
that same suffix is exactly what a naive `*.csv` package-data line misses.
When you add a new data extension, add it to `package-data` in the same
commit, then verify against an **installed** copy rather than the source tree.

## Releases

`CHANGELOG.md` accumulates under `[Unreleased]`; a release cut moves it to a
version section and bumps `pyproject.toml`. Because the main repo consumes
the wheel, a release is what actually propagates work beyond a local install
— unreleased work is invisible to every other consumer.

See [[issues-and-changelog]] for what earns a CHANGELOG line, and
[[spec-fidelity]] for the standing constraint on what release notes may claim
about protocol support that has not been simulation-exercised.
