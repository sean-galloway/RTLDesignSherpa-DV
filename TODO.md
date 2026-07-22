# BFM / Monitor Methodology TODO

Derived from a methodology review of `src/CocoTBFramework/components/` (BFM/Monitor layer on top of `cocotb` + `cocotb_bus`).

Each item below is **GitHub-Issue ready**: copy the title, labels, and body into a new issue. Because this package is on PyPI (`cocotb-framework`), every change needs a tracked issue, a PR, a CHANGELOG entry, and a release.

Current published version: **0.5.0** (see `pyproject.toml`).

> **Status update:** all nine items in the first section shipped — items 8/9 as
> documentation audits and items 1-7 as refactors — in release **0.2.0** (see
> `CHANGELOG.md`). That section is retained as the issue-drafting record.
>
> **Open work:** see [DFI BFM Capability Parity](#dfi-bfm-capability-parity)
> below (items D1–D11, not started).

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

## DFI BFM Capability Parity

Derived from a 2026-07 gap analysis of `components/dfi/` against the mature BFM
families (`axi4/`, `gaxi/`, `apb/`). DFI is **ahead** of the other families on
protocol depth — JEDEC timing models (`jedec_timings.py` + CSVs), the stateful
`DramStateModel` with a categorized `ViolationPolicy`, the per-spec-version
Strategy/Registry in `behaviors/`, address mapping and LPDDR2 CA encode/decode,
and multi-strategy read servers. None of that should be regressed. What it lacks
is the *ergonomic* layer every other family has.

### Parity Tracking Table

| # | Title | Effort | Depends on | Status |
|---|---|---|---|---|
| D1 | Wire `FlexRandomizer` into `DFIMasterMC` command/beat spacing | S | — | Not started |
| D2 | Adopt `MasterStatistics` / `MonitorStatistics` | S | — | Not started |
| D3 | Add `dfi_factories.py` | S | — | Not started |
| D4 | Rebase DFI packets on shared `Packet` | M | — | Not started |
| D5 | `DFISequence` DRAM-aware workload generator | M | D1, D4 | Not started |
| D6 | Fold `DFIScoreboard` onto `BaseScoreboard` + transformer | M | D4 | Not started |
| D7 | `DFIRandomizationConfig` profiles | M | D1, D3 | Not started |
| D8 | Signal auto-discovery via `SignalResolver` | M/L | — | Not started |
| D9 | DFI handshake protocol-assertion checker | S | — | Not started |
| D10 | Coverage hooks + wavedrom binding | S | D3 | Not started |
| D11 | Docs build-out (per-class pages + index) | S/M | D1–D7 | Not started |

**Suggested order:** D1 → D2 → D3 (independent, immediate ROI), then D4 → D5 →
D6 → D7 (the packet rebase unblocks sequence and scoreboard), then D8–D11 as
capacity allows.

**Highest-leverage item is D1.** DFI already owns the thing the other families
lack — the `DramStateModel` violation checker — so randomized stimulus becomes
immediately self-checking the moment there is randomized stimulus to check.

### D1 — Wire `FlexRandomizer` into `DFIMasterMC`

**Labels:** `enhancement`, `area:dfi`
DFI has zero randomization anywhere today. Add an optional `randomizer` kwarg
mirroring `gaxi_master.py` (which drives delays via `randomizer.next()`), and
replace fixed `nop(cycles)` gaps between commands with randomizer-driven delays.
Acceptance: constrained-random command spacing that `DramStateModel` polices;
existing deterministic tests unaffected when no randomizer is passed.

### D2 — Adopt shared statistics classes

**Labels:** `enhancement`, `area:dfi`
`DFISlavePHY` / `DFIMonitor` / `DFIMasterMC` use manual integer counters
(`writes_committed`, `reads_served`, `command_count`, …). Replace with
`MasterStatistics` / `MonitorStatistics` (`shared/master_statistics.py`,
`monitor_statistics.py`) and `record_*` calls, keeping the DRAM-specific counters
as extra fields. Note: `reads_served` semantics differ between the strict and
free-running read paths — resolve that while migrating (see audit finding).

### D3 — `dfi_factories.py`

**Labels:** `enhancement`, `dx`, `area:dfi`
No factory module exists. Add `create_dfi_master`, `create_dfi_slave_phy`,
`create_dfi_monitor`, `create_dfi_scoreboard`, `create_dfi_components(dut, clock, …)`
mirroring `gaxi_factories.py`. Pure assembly, low risk, large usability win.
**Note the audit lesson:** the other families' factories shipped broken because
nothing tested them — add unit tests that actually call each factory.

### D4 — Rebase DFI packets on shared `Packet`

**Labels:** `refactor`, `area:dfi`
`DFIControlPacket` / `DFIWriteDataPacket` / `DFIReadDataPacket` are bare
dataclasses, so they get no pack/unpack, no field cache, no randomization hooks,
and cannot flow through the shared scoreboard/transformer machinery.
`dfi_field_configs.py` already builds `FieldConfig`s that are not fed to a
Packet-based path. Churn lands in the monitor/master construction sites.

### D5 — `DFISequence`

**Labels:** `enhancement`, `area:dfi`
Model on `AXI4Sequence`. Primitives (`add_activate/read/write/precharge/refresh`)
plus DRAM-aware generators — `add_row_hit_burst`, `add_bank_spray`,
`add_row_miss_pair`, `add_random_workload` — using `AddressMapping` for legal
bank/row/col spraying.

### D6 — `DFIScoreboard` onto `BaseScoreboard`

**Labels:** `refactor`, `area:dfi`
Today it is standalone and event-driven with no expected/actual compare. Keep the
event-callback surface, add an expected-vs-actual path (master-issued commands vs
monitor-observed; write-then-read integrity via `MemoryModel`) and a
`DFItoMemoryAdapter` analogous to `GAXItoMemoryAdapter`. Fold in the audit finding
that `poll()` offsets go stale if slave queues are cleared — add a reset/resync hook.

### D7 — `DFIRandomizationConfig`

**Labels:** `enhancement`, `area:dfi`
Profiles in the spirit of `AXI4RandomizationConfig`: traffic-heavy,
refresh-stress, training-heavy, compliance.

### D8 — `SignalResolver` adoption

**Labels:** `refactor`, `area:dfi`
All three DFI roles build fixed `_signals` lists against hardcoded `mc_dfi` /
`phy_dfi` prefixes — no auto-discovery, no per-version optional-signal sets.
Structural: touches master, slave and monitor together.

### D9 — DFI handshake assertion checker

**Labels:** `enhancement`, `area:dfi`
Complements (does not replace) `DramStateModel`, which checks the DRAM side. Check
req/ack legality for `ctrlupd`, `phyupd`, freq-change, disconnect and `phymstr`.
The event queues already exist to build on.

### D10 — Coverage hooks + wavedrom

**Labels:** `enhancement`, `area:dfi`
Port the `gaxi/coverage_hooks.py` pattern; add wavedrom binding for the 33 DFI
signals per side.

### D11 — Docs build-out

**Labels:** `docs`, `area:dfi`
DFI has one overview page; `gaxi/` has 11 and `axi4/` has 7. Add an index plus
per-class pages (master, slave-PHY, monitor, timing/JEDEC, dram-state, behaviors,
scoreboard, sequence once built). Sequence last so docs do not churn.

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
