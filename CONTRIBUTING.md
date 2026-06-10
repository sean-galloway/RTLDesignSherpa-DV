# Contributing to RTLDesignSherpa-DV

Thanks for your interest in improving the cocotb-framework. This repo is a
reusable verification library: BFMs, scoreboards, and TB helpers used by
the parent [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa)
project and (we hope) by other RTL verification efforts.

This guide covers the basics: how to file a useful bug report, propose a
feature, and submit a pull request.

---

## Filing issues

Before opening a new issue, please search [existing issues](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues?q=is%3Aissue)
for duplicates.

There are three issue templates:

- **Bug report** — something doesn't behave the way the docs say it should.
- **Feature request** — a new BFM, scoreboard, or framework capability.
- **Question / discussion** — usage questions, design discussions, "is this
  the right way to model X?" The answer may end up shaping the docs or
  spawning a feature request, so questions are welcome.

For bug reports, include:

- Python version, cocotb version (`pip show cocotb`), and simulator + version
  (`verilator --version`, etc.)
- A minimal reproducer if you can — even a 20-line snippet beats a paragraph
  of description.
- The full traceback / log, not just the last line.

---

## Development setup

```bash
git clone https://github.com/sean-galloway/RTLDesignSherpa-DV.git
cd RTLDesignSherpa-DV
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev,all]"

# Optional: Tier 2 sim tests (need a Verilog simulator on PATH)
pip install -e ".[sim]"
```

The repo ships an `env_python` script that activates the venv and wires
`PYTHONPATH` so source edits are picked up without a reinstall:

```bash
source env_python
```

---

## Running tests

```bash
# Tier 1 — pure-Python unit tests (no simulator required)
pytest tests/unit/ -v

# Tier 2 — cocotb sim tests (need verilator + the RTL repo)
pytest tests/sim/ -v
```

If you add new BFM behavior, please add a test that exercises it. If you
fix a bug, please add a regression test that fails before your fix and
passes after.

---

## Code style

- Python: [ruff](https://github.com/astral-sh/ruff) — run `ruff check src/`
  before committing. The repo's `pyproject.toml` defines the active rule
  set.
- Line length: 120 (per `pyproject.toml`).
- Prefer small, focused commits with a clear `type(scope): description`
  subject line. Examples from the existing log:

  ```
  feat(dfi): MVP foundation — signal envelope, packets, field configs
  fix(axi4): correct handling of NARROW burst sizes
  chore(ci): bump GitHub Actions to Node 24 versions
  ```

Types we use: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

---

## Pull request workflow

1. **Open an issue first** for anything larger than a typo or a one-line
   fix. This lets us agree on the approach before you sink time into code.
2. Fork the repo and create a feature branch off `main`:
   ```
   git checkout -b feat/short-description
   ```
3. Make your change. Add tests. Run `pytest` and `ruff check`.
4. Push and open a PR against `main`. Reference the issue (`Closes #N` or
   `Refs #N`).
5. CI runs automatically. Please keep it green — a red PR is much harder
   to review.

PRs that touch BFM semantics or break existing test interfaces will get
extra scrutiny, since downstream projects depend on this repo as a pinned
version.

---

## Code of Conduct

By participating, you agree to abide by the project's
[Code of Conduct](./CODE_OF_CONDUCT.md).

---

## License

This project is MIT-licensed. Contributions are accepted under the same
terms — see [LICENSE](./LICENSE).
