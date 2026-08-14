---
title: Tests and tooling in this repo
summary: The unit/sim split, why you source env_python, testing classes that need a live cocotb entity, and scoping ruff so it does not rewrite eighty unrelated files.
---

# Tests and tooling in this repo

## Two test trees, two purposes

- `tests/unit/` — plain pytest, no simulator. Fast (the whole suite runs in
  about a second), so it runs on every increment.
- `tests/sim/` — cocotb against RTL, needs a simulator and a DUT.

Protocol logic — encodings, state rules, packing — should be reachable from
`tests/unit/`. When it is, a spec question gets answered in a second instead of
a simulation, and it stays answerable in a repo that has no DUT for that
protocol at all.

## Running them

```bash
source env_python && python3 -m pytest -q tests/unit/
```

Source `env_python`, not the bare venv activate: the plain activate does not
set the paths the suite needs. In the main repo the equivalent is the
`ptw`/`ptwp`/`ptg`/`ptf` aliases, and the env you source must match the repo
the test lives in.

Two operational notes that have each cost real time:

- **The shell's working directory persists between commands.** A `cd` into a
  subdirectory in one command leaves you there for the next, and
  `source env_python` then fails silently because the file is not in scope —
  producing confusing failures that look like broken tests.
- **Clean before a sim run.** `make clean-all` in the test directory first, so
  a stale `sim_build` cannot mask the result. A suspiciously fast run is the
  tell; a reverted-RTL run against a stale build is meaningless.

## Testing something that needs a live cocotb entity

`DFISlavePHY` and friends cannot be constructed without a DUT handle, which
would put their logic out of unit-test reach. Two ways out, in order:

1. **Keep the logic outside the class.** The CA-bus work put streaming and
   dispatch in `ca_stream.py` / `ca_dispatch.py`, testable directly, leaving
   the BFM a thin adapter. This is the better answer whenever it is available.
2. **Exercise methods on a bare instance.** `object.__new__(DFISlavePHY)` plus
   only the attributes the method under test touches, with a stub bus object
   and the collaborating method replaced by a recorder. Legitimate for pinning
   glue — signal selection, dispatch bookkeeping — and it is what
   `tests/unit/test_dfi_slave_ca_bus.py` does.

## Scope the formatter, or it will scope itself

`ruff check --fix src/` is safe. `ruff check --fix tests/` is **not** — this
repo carries pre-existing lint debt in `tests/sim/`, and a single unscoped
`--fix` rewrote 344 findings across 82 files that had nothing to do with the
change in flight. Recovering meant listing tracked-modified files, filtering
out the intended ones, and restoring the rest.

Fix your own files by name:

```bash
ruff check --fix src/ tests/unit/test_thing.py
```

Then confirm with `git status --short` that the diff is only what you touched,
**before** staging. Note that `git status --short | awk '{print $2}'` also
catches untracked sim artifacts; filter on the `^ M` prefix when you mean
tracked-and-modified.

## The success bar

RTL is deterministic, so a partial pass is a bug, not noise: the standing rule
is 100% success. A flaky-looking result is a real defect — in the RTL, the
BFM, or the test — and "it passes on a rerun" is a finding to chase, not a
result to accept.
