<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. Move a task between pages by cutting its block, do not copy. -->

# dfi — Open (accepted, not started)

---

## DFI-007 — Wire CA decode into `DFIMonitor`
**Status:** open 2026-08-13 — the slave-PHY half shipped (DFI-005), monitor did not

`DFISlavePHY` decodes the encoded CA bus via an opt-in `ca_map=`
([[DFI-005]]), but `DFIMonitor._decode_command` (`dfi_monitor.py:170`) is
still `_CMD_DECODE.get((ras, cas, we))` — pure ras/cas/we. It does not
handle a CA bus at *all*: not the v5/v6 maps, and not even the LPDDR2 CA
decoder the slave has had for some time. So a monitor attached to any
CA-bus DUT silently reports every command as NOP.

The pieces are already built and tested: construct a `CAStream` (or
`HBM4CAStreams`) the same way the slave does and feed `dfi_cmdaddr` once
per cycle. Two monitor-specific details:

- Construct the decoder with `strict=False`. A monitor may attach
  mid-command, and an orphan ACT-2 or an unrecognized head edge should
  resync (the `resyncs` counter is already there for this) rather than
  raise the way it correctly does in a slave.
- The monitor emits packets rather than driving a state model, so it
  wants the decoded `args` dict directly, not the `(bank, addr)` fold
  `args_to_legacy_addr` does for the slave's command handler.

**Acceptance:** a monitor with a `ca_map` reports the same command
sequence a slave sees for the same stimulus; without one, behaviour is
bit-identical to today.

## DFI-008 — `dram_state` v6.0 semantics
**Status:** open 2026-08-13

`DramStateModel` encodes DDR2/3-era state rules. DFI v6.0 dropped
DDR1–4 and LPDDR1–4 entirely and the surviving protocols differ in ways
the model does not represent — per-bank vs per-pseudo-channel refresh
accounting (HBM4 Table 3 counts array timings individually per pseudo
channel), sub-channel selects (LPDDR5/6 `sc`), dual-bank refresh
(LPDDR6 `dbg`), and refresh-management commands as a distinct class
rather than a plain REF.

The decoded args already carry these fields — `ca_dispatch` passes
`pc`, `sid`, `sc`, `dbg`, `rfm` through untouched — so this is state-model
work, not decode work. Scope it against what the maps already deliver.

## DFI-009 — Express the LPDDR2 CA encoding as a `CAMap`
**Status:** open 2026-08-13 — consistency win, no behaviour change intended

`lpddr_ca.py` hand-codes JESD209-2F Table 60. It is deliberately the
**single source of truth** shared with the RTL command formatter
(`pumice-ddr2-lpddr2/rtl/fub/dfi_cmd_formatter.sv`), and a conformance
test decodes the RTL's output against it — so it must not simply be
deleted.

Do what HBM4 did: add an `LPDDR2_CA_MAP` and differentially test it
bit-for-bit against the existing hand codec, keeping the hand codec as
the spec anchor. That gets LPDDR2 onto the same streaming/dispatch path
as every other protocol and lets the slave's LPDDR2 branch collapse into
the general CA path.

**Watch:** LPDDR2 scrambles the row/column address across both CA edges,
which is exactly what `BitRun` lists express — but the scramble is a JEDEC
requirement (§2.14.1), so any map must reproduce it exactly, not tidily.

## DFI-010 — Cut the 0.6.4 release
**Status:** open 2026-08-13

`CHANGELOG.md` `[Unreleased]` has accumulated since 0.6.3 (2026-08-09):
the whole CA-map stack (DFI-001…005) plus the HBM4 work (DFI-006).
The main repo consumes this package as a built wheel, so a release is
what actually propagates it beyond the local editable install.

**Note the standing constraint:** do not advertise the LPDDR/multi-version
DFI features in release notes until fresh-design validation lands — the
maps are spec-verified but not simulation-exercised ([[DFI-023]]).

---

## BFM capability parity (migrated from `TODO.md`, 2026-08-13)

From a 2026-07 gap analysis of `components/dfi/` against the mature BFM
families (`axi4/`, `gaxi/`, `apb/`). DFI is **ahead** of the others on
protocol depth — JEDEC timing models, the stateful `DramStateModel` with a
categorized `ViolationPolicy`, the per-spec-version Strategy/Registry in
`behaviors/`, address mapping, and multi-strategy read servers. None of that
should be regressed. What it lacks is the *ergonomic* layer every other
family has.

**Suggested order:** DFI-011 → 012 → 013 (independent, immediate ROI), then
014 → 015 → 016 → 017 (the packet rebase unblocks sequence and scoreboard),
then 018–021 as capacity allows.

**Highest-leverage item is DFI-011.** DFI already owns the thing the other
families lack — the `DramStateModel` violation checker — so randomized
stimulus becomes self-checking the moment there is randomized stimulus.

## DFI-011 — Wire `FlexRandomizer` into `DFIMasterMC` (was D1)
**Status:** open 2026-08-13 (raised 2026-07) — effort S, no deps

DFI has zero randomization anywhere today. Add an optional `randomizer`
kwarg mirroring `gaxi_master.py` (which drives delays via
`randomizer.next()`), and replace fixed `nop(cycles)` gaps between
commands with randomizer-driven delays.
**Acceptance:** constrained-random command spacing that `DramStateModel`
polices; existing deterministic tests unaffected when no randomizer is
passed.

## DFI-012 — Adopt the shared statistics classes (was D2)
**Status:** open 2026-08-13 (raised 2026-07) — effort S, no deps

`DFISlavePHY` / `DFIMonitor` / `DFIMasterMC` use manual integer counters
(`writes_committed`, `reads_served`, `command_count`, …). Replace with
`MasterStatistics` / `MonitorStatistics` (`shared/master_statistics.py`,
`monitor_statistics.py`) and `record_*` calls, keeping the DRAM-specific
counters as extra fields.
**Resolve while migrating:** `reads_served` means different things on the
strict and free-running read paths (audit finding).

## DFI-013 — Add `dfi_factories.py` (was D3)
**Status:** open 2026-08-13 (raised 2026-07) — effort S, no deps

No factory module exists. Add `create_dfi_master`, `create_dfi_slave_phy`,
`create_dfi_monitor`, `create_dfi_scoreboard`, and
`create_dfi_components(dut, clock, …)` mirroring `gaxi_factories.py`. Pure
assembly, low risk, large usability win.
**Note the audit lesson:** the other families' factories shipped broken
because nothing tested them — add unit tests that actually call each one.
A factory is also the natural place to accept a `ca_map` ([[DFI-005]]).

## DFI-014 — Rebase DFI packets on the shared `Packet` (was D4)
**Status:** open 2026-08-13 (raised 2026-07) — effort M

DFI packet types are standalone rather than built on the shared `Packet` /
`FieldConfig` machinery, so they miss the formatting, comparison, and
randomization the other families get for free. Unblocks DFI-015 and 016.

## DFI-015 — `DFISequence` DRAM-aware workload generator (was D5)
**Status:** open 2026-08-13 (raised 2026-07) — effort M, depends on DFI-011, DFI-014

A sequence layer that generates DRAM-aware traffic (page hit/miss mixes,
bank interleave, refresh pressure) rather than hand-written command lists.

## DFI-016 — Fold `DFIScoreboard` onto `BaseScoreboard` + transformer (was D6)
**Status:** open 2026-08-13 (raised 2026-07) — effort M, depends on DFI-014

## DFI-017 — `DFIRandomizationConfig` profiles (was D7)
**Status:** open 2026-08-13 (raised 2026-07) — effort M, depends on DFI-011, DFI-013

Named profiles (stress, light, page-thrash) rather than ad-hoc constraints.

## DFI-018 — Signal auto-discovery via `SignalResolver` (was D8)
**Status:** open 2026-08-13 (raised 2026-07) — effort M/L

DFI wires signals by explicit name; every other family resolves them.
Note this interacts with the v6.0 `dfi_address` → `dfi_cmdaddr` rename,
which the CA path currently handles with a two-name fallback
(`_ca_bus_word`) that a resolver should subsume.

## DFI-019 — DFI handshake protocol-assertion checker (was D9)
**Status:** open 2026-08-13 (raised 2026-07) — effort S

## DFI-020 — Coverage hooks + wavedrom binding (was D10)
**Status:** open 2026-08-13 (raised 2026-07) — effort S, depends on DFI-013

## DFI-021 — Docs build-out: per-class pages + index (was D11)
**Status:** open 2026-08-13 (raised 2026-07) — effort S/M, depends on DFI-011…017

Should now also cover the CA-map stack: how to write a device map, what
`camap_from_dict` expects, and the streaming/dispatch split.
