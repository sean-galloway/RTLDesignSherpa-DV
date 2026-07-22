# BFM / Monitor Methodology TODO

Derived from a methodology review of `src/CocoTBFramework/components/` (BFM/Monitor layer on top of `cocotb` + `cocotb_bus`).

Each item below is **GitHub-Issue ready**: copy the title, labels, and body into a new issue. Because this package is on PyPI (`cocotb-framework`), every change needs a tracked issue, a PR, a CHANGELOG entry, and a release.

Current published version: **0.5.0** (see `pyproject.toml`).

> **Status update:** all nine items below shipped — items 8/9 as documentation
> audits and items 1-7 as refactors — in release **0.2.0** (see
> `CHANGELOG.md`). This file is retained as the issue-drafting record; new
> work is tracked directly in GitHub issues.

---

## Tracking Table

| # | Title | Severity | Target | Breaking? | Issue | PR | Status |
|---|---|---|---|---|---|---|---|
| 1 | Merge `FIFOComponentBase` into `GAXIComponentBase` | High | 0.2.0 | Yes (internal hierarchy) | [#6](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/6) | — | Shipped in 0.2.0 |
| 2 | `AXISSlave` should inherit `GAXISlave`, not `GAXIMonitorBase` | High | 0.2.0 | Yes (MRO change) | [#7](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/7) | — | Shipped in 0.2.0 |
| 3 | Extract APB / APB5 common base | Medium | 0.2.0 | No (additive) | [#8](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/8) | — | Shipped in 0.2.0 |
| 4 | Consolidate `protocol_type` enum into single source of truth | Medium | 0.2.0 | No | [#9](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/9) | — | Shipped in 0.2.0 |
| 5 | Extract `_pop_custom_kwargs` helper for cocotb-parent init dance | Low | 0.2.0 | No | [#10](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/10) | — | Shipped in 0.2.0 |
| 6 | Add type annotations to GAXI/FIFO base-class signatures | Low | 0.2.0 | No | [#11](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/11) | — | Shipped in 0.2.0 |
| 7 | Document or rename the "Slave-via-BusMonitor" pattern | Low | 0.2.0 | Maybe (if renamed) | [#12](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/12) | — | Shipped in 0.2.0 |
| 8 | Audit `AXI4SlaveRead._ar_callback` for in-order dict races | High | 0.1.2 | No | [#13](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/13) | — | Shipped in 0.2.0 |
| 9 | Audit `AXI4SlaveWrite` shared mutable state across AW/W callbacks | High | 0.1.2 | No | [#14](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/14) | — | Shipped in 0.2.0 |

Severity = correctness impact. Target = proposed release. Breaking = SemVer breaking (0.x allows breaking changes but downstream users should be warned via CHANGELOG).

### Release plan suggestion

- **0.1.2** (patch): items 8, 9 — concurrency audit fixes only, no API change.
- **0.2.0** (minor, may include breakage): items 1–7 — internal class hierarchy consolidation. Document migration notes for any user code that subclasses `FIFOComponentBase`, `AXISSlave`, or `APBSlave` directly.

---

## Per-Issue Drafts

### Issue 1 — Merge `FIFOComponentBase` into `GAXIComponentBase`

**Labels:** `refactor`, `tech-debt`, `breaking-change`, `area:components`
**Severity:** High (active duplication, divergence risk)
**Target:** 0.2.0

**Problem.** `src/CocoTBFramework/components/fifo/fifo_component_base.py:34` and `src/CocoTBFramework/components/gaxi/gaxi_component_base.py:36` are ~95% identical: same constructor signature, same `SignalResolver` wiring, same `complete_base_initialization`, same `_setup_data_strategies`. They were forked rather than extracted from a common base. The only material divergence is the `protocol_type` validation set (`gaxi_component_base.py:98-111` lists ~26 channel types; FIFO accepts only `fifo_master` / `fifo_slave`).

Bug fixes and improvements applied to one base do not propagate to the other.

**Proposed fix.** Either:
- (a) Rename `GAXIComponentBase` → `ReadyValidComponentBase`, add `fifo_master` / `fifo_slave` to the accepted `protocol_type` set, and change `FIFOMaster`/`FIFOSlave`/`FIFOMonitor` to inherit from it. Keep `GAXIComponentBase` as a deprecation-shim alias for one minor release.
- (b) Keep the `GAXIComponentBase` name and add FIFO protocol types to its enum; `FIFOComponentBase` becomes a deprecated alias.

Recommend (b) — less code churn.

**Acceptance criteria.**
- [ ] `fifo/fifo_component_base.py` deleted or reduced to a deprecation shim
- [ ] `FIFOMaster` / `FIFOSlave` / `FIFOMonitor` inherit from the unified base
- [ ] Existing FIFO tests pass without modification
- [ ] CHANGELOG notes the inheritance change under "Breaking" or "Internal"
- [ ] If a deprecation shim is kept, it emits `DeprecationWarning`

**Breaking change risk.** User code that does `isinstance(x, FIFOComponentBase)` or subclasses it directly will need to update. Document in CHANGELOG migration notes.

---

### Issue 2 — `AXISSlave` should inherit `GAXISlave`, not `GAXIMonitorBase`

**Labels:** `bug`, `refactor`, `area:axis`
**Severity:** High (functional inconsistency)
**Target:** 0.2.0

**Problem.** `axis4/axis_slave.py:32` declares `class AXISSlave(GAXIMonitorBase)`, bypassing `GAXISlave`. As a consequence:
- AXISSlave reimplements `_monitor_recv` (`axis_slave.py:119`) instead of reusing the GAXI receive-pipeline state machine.
- AXISSlave does not get the `pipeline_debug` plumbing that `GAXISlave` exposes.
- Ready-driving logic that lives in `GAXISlave` is forked into AXIS code.

This is almost certainly accidental — AXIS is a ready/valid protocol just like every other GAXI consumer.

**Proposed fix.** Change `AXISSlave` to inherit from `GAXISlave`. Move any AXIS-specific overrides into hook methods on `GAXISlave` if needed. Verify AXIS5's slave (if it exists) propagates the change correctly.

**Acceptance criteria.**
- [ ] `AXISSlave` inherits from `GAXISlave`
- [ ] `_monitor_recv` override removed or reduced to TLAST/frame-tracking deltas
- [ ] `pipeline_debug` works on AXIS slaves
- [ ] AXIS tests still pass; add a test that exercises the pipeline-debug path on AXIS

**Breaking change risk.** MRO change. Users doing `isinstance(x, GAXIMonitorBase)` will still match (transitively through `GAXISlave`), so most user code is safe. Document anyway.

---

### Issue 3 — Extract APB / APB5 common base

**Labels:** `refactor`, `tech-debt`, `area:apb`
**Severity:** Medium
**Target:** 0.2.0

**Problem.** `apb/apb_components.py` and `apb5/apb5_components.py` share ~80% of pipeline code (transmit state machine, edge detection in monitor, ready-delay/error-injection in slave). APB5 is currently a copy with extended signal lists and user/parity fields. Fixes to APB do not propagate to APB5.

**Proposed fix.** Extract an `APBCommonMaster` / `APBCommonSlave` / `APBCommonMonitor` base into a shared module (either a new `components/apb_common/` or under `components/shared/apb_base.py`). APB and APB5 become thin subclasses that supply signal lists and field configs.

**Acceptance criteria.**
- [ ] Shared base classes added
- [ ] `apb/apb_components.py` and `apb5/apb5_components.py` reduced to deltas
- [ ] Public class names (`APBMaster`, `APBSlave`, `APBMonitor`, `APB5Master`, etc.) preserved
- [ ] Existing APB and APB5 tests pass without modification

**Breaking change risk.** Low if public class names are preserved. Internal subclassing chains change.

---

### Issue 4 — Consolidate `protocol_type` enum into single source of truth

**Labels:** `refactor`, `tech-debt`, `area:components`
**Severity:** Medium
**Target:** 0.2.0 (alongside Issue 1)

**Problem.** The accepted-`protocol_type` list is hard-coded in two places: `gaxi_component_base.py:98-111` and `fifo_component_base.py:95`. Adding a new channel type requires editing both. This drift is the root cause of Issue 1's divergence.

**Proposed fix.** Move the canonical list to `components/shared/protocol_types.py` as a `Literal[...]` type alias or `frozenset[str]`. Both base classes import it.

**Acceptance criteria.**
- [ ] Single `protocol_types.py` (or equivalent) module
- [ ] All `protocol_type` validation reads from that module
- [ ] Adding a new channel requires editing exactly one file

---

### Issue 5 — Extract `_pop_custom_kwargs` helper for cocotb-parent init dance

**Labels:** `refactor`, `dx`, `area:components`
**Severity:** Low
**Target:** 0.2.0

**Problem.** The cocotb-parent init pattern (`kwargs.pop('bus_name', '')`, `kwargs.pop('pkt_prefix', '')`, etc., before calling `BusDriver.__init__` with an empty prefix, then `complete_base_initialization(bus)`) is duplicated in:
- `gaxi_master.py:117-127`
- `gaxi_slave.py:73-78`
- `gaxi_monitor_base.py:70-77`
- `fifo/fifo_master.py`, `fifo/fifo_slave.py`, `fifo/fifo_monitor.py`

Every new custom kwarg has to be added in 3+ places.

**Proposed fix.** Add `_pop_custom_kwargs(kwargs, names: list[str]) -> dict` (or a template-method on the base) that pops and returns the framework-specific kwargs. Each BFM `__init__` becomes one call.

**Acceptance criteria.**
- [ ] Helper added to `shared/` or to the unified base class
- [ ] All ~6 BFM `__init__` methods use the helper
- [ ] Adding a new framework kwarg requires editing one file (the helper or base)

---

### Issue 6 — Add type annotations to GAXI/FIFO base-class signatures

**Labels:** `dx`, `types`, `area:components`
**Severity:** Low
**Target:** 0.2.0

**Problem.** `GAXIComponentBase.__init__` (`gaxi_component_base.py:50`) and most BFM `__init__` signatures are untyped. Project Python style requires type hints. Downstream BFM authors get no IDE assistance when subclassing.

**Proposed fix.** Add full type annotations to:
- `GAXIComponentBase.__init__` and its public methods
- `GAXIMaster`, `GAXISlave`, `GAXIMonitorBase`, `GAXIMonitor` `__init__`
- `FIFOComponentBase` and FIFO BFMs (or, post-Issue 1, the unified base)
- Shared primitives (`FieldConfig`, `Packet`, `FlexRandomizer`, `MemoryModel`) — confirm coverage and fill gaps

Run `ruff check` and `mypy` (if configured) before merge.

**Acceptance criteria.**
- [ ] All public `__init__` signatures and methods on the base classes typed
- [ ] `ruff check src/` clean
- [ ] No runtime regressions in existing tests

---

### Issue 7 — Document or rename the "Slave-via-BusMonitor" pattern

**Labels:** `docs`, `dx`, `area:apb`, `area:gaxi`
**Severity:** Low
**Target:** 0.2.0

**Problem.** `APBSlave(BusMonitor)` (`apb_components.py:153`) and `GAXISlave` (transitively) drive output signals despite inheriting from `cocotb_bus.BusMonitor`, which is semantically a passive observer. This is non-obvious to anyone new. `GAXISlave` has a docstring note; `APBSlave` does not.

**Proposed fix.** Either:
- (a) Add a docstring note to `APBSlave` and any other slave class missing one explaining why `BusMonitor` is the base.
- (b) Introduce `APBResponder` / `GAXIResponder` aliases (preferred long-term name) while keeping the `Slave` names as deprecated aliases.

Recommend (a) for 0.2.0; revisit (b) at 1.0.0.

**Acceptance criteria.**
- [ ] Every Slave-class that inherits `BusMonitor` has a docstring explaining the pattern
- [ ] CONTRIBUTING.md or docs/overview.md gains a short "BFM class conventions" section

---

### Issue 8 — Audit `AXI4SlaveRead._ar_callback` for in-order dict races

**Labels:** `bug`, `concurrency`, `area:axi4`
**Severity:** High (potential silent race)
**Target:** 0.1.2

**Problem.** `axi4_interfaces.py:543` (`AXI4SlaveRead._ar_callback`) installs a callback that triggers R bursts and touches `in_order_active` / `in_order_queue` dicts (`axi4_interfaces.py:508-509`). If overlapping AR transactions with the same ID can race on these dicts without a `cocotb.triggers.Lock`, this is the same bug class as the `completion_locks` issue that was fixed in commit `9d6cbc9`.

**Proposed fix.** Audit the AR callback path:
1. Confirm whether `in_order_active` / `in_order_queue` are touched only from callbacks (serialized by cocotb scheduler) or also from `await`-suspending coroutines.
2. If touched from any `await`-suspending path, wrap mutations with a `cocotb.triggers.Lock`.
3. Either way: add a comment documenting the synchronization assumption, matching the comment style at `axi4_interfaces.py:117-128` and `:315-325`.

**Acceptance criteria.**
- [ ] Audit notes recorded in the issue or PR
- [ ] Lock added if races are possible
- [ ] Synchronization assumption documented in source
- [ ] Add a concurrency stress test if practical (multiple overlapping ARs with same ID)

---

### Issue 9 — Audit `AXI4SlaveWrite` shared mutable state across AW/W callbacks

**Labels:** `bug`, `concurrency`, `area:axi4`
**Severity:** High (potential silent race)
**Target:** 0.1.2

**Problem.** `axi4_interfaces.py:962-963` (`AXI4SlaveWrite.orphaned_w_packets` and `w_transaction_queue`) are touched from both `_aw_callback` and `_w_callback`. Today cocotb serializes callbacks, so the dict mutations are safe — but any `await` mid-mutation in either callback would invert ordering and break the invariant silently.

**Proposed fix.**
1. Audit `_aw_callback` and `_w_callback` for any `await`-suspending calls between mutations of these structures.
2. If any are present, wrap with `cocotb.triggers.Lock` (consistent with `axi4_interfaces.py:325` and `:1305`).
3. Either way, add a comment asserting "callbacks must not await between mutations of `orphaned_w_packets` / `w_transaction_queue`."

**Acceptance criteria.**
- [ ] Audit recorded
- [ ] Lock added if races are possible
- [ ] Source comment documents the invariant
- [ ] Add a stress test where AW and W arrive interleaved across multiple IDs

---

## Workflow notes (for contributors)

1. File each issue using the title and body above. Tag with the listed labels.
2. One PR per issue (don't bundle the 0.2.0 refactors — they have independent risk profiles).
3. Every PR must:
   - Update `CHANGELOG.md` under the target version section
   - Bump `pyproject.toml:7` only on the release-cutting PR, not per-feature PR
   - Add or update tests
   - Pass `ruff check src/` and `pytest`
4. Release-cut PR: tag `v0.1.2` / `v0.2.0`, build with `python -m build`, publish to PyPI.
