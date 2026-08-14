<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. Move a task between pages by cutting its block, do not copy. -->

# dfi — Deferred (accepted, parked on a named external condition)

Everything here is shaped and ready; starting it today would be wrong
because the named condition is not met. Each block must say what un-defers
it.

---

## DFI-022 — Real HBM4 timing profile
**Status:** deferred 2026-08-13 — **un-defers when:** a vendor HBM4 datasheet
(SK hynix / Samsung / Micron) is available on disk

JESD270-4A leaves the core array timing *values* vendor-defined — the
min/max columns in Table 108 are blank in the standard itself. Only a
handful are spec-fixed (tREFI = 3.9 µs, tPPD = 2 CK, tCKSRX = 5 CK), and
those are already filled in.

The fill-in sheet is in place at
`src/CocoTBFramework/components/dfi/jedec/hbm4-template.csv.example`: the
15 loader-required rows plus the HBM4-native split parameters (tRCDRD /
tRCDWR, tRRDL / tRRDS, tRFCab / tRFCpb, tCCDL / S / R), each marked
`FILL_ME`. A unit test substitutes dummy values and runs the real loader,
so the template cannot rot while it waits.

**Do not invent the numbers.** The spec-verified rule for this area is that
timing, signal, and command content must be grounded in an on-disk
specification. Copy from a datasheet, or leave `FILL_ME`.

## DFI-023 — Exercise the v5/v6 CA path in simulation
**Status:** deferred 2026-08-13 — **un-defers when:** a v5/v6-era DUT exists to
run against

The whole CA stack (DFI-001…006) is unit-tested — golden vectors derived
from the JEDEC truth tables, differential tests against the hand-written
codecs, streaming and dispatch tests per protocol — but it has **never run
against RTL**. There is no v5/v6 co-simulation target in either repo: the
existing DFI co-sim is pumice, which is DDR2/LPDDR2 on DFI 2.1.

This is the honest gap behind the standing rule not to advertise the
LPDDR/multi-version DFI features in release notes ([[DFI-010]]). Spec-verified
is not the same as silicon-verified, and neither is the same as
simulation-exercised.

Candidate un-deferring events, in rough order of likelihood:
- the fresh DDR2/3/4 + LPDDR2/3/4 designs planned for ~2026-09/10 — these
  raise the validation bar but are mostly *older* DFI versions, so they
  would exercise the CA path only via [[DFI-009]] (LPDDR2 as a map);
- a v6-era controller or a vendor PHY model to run the BFM against.

---

## Parked 2026-08-14: the whole DFI protocol/BFM programme

**Un-defers when:** the memory-controller work that consumes these BFMs
starts — the fresh DDR2/3/4 + LPDDR2/3/4 designs, or a v5/v6-era
controller. Owner's steer, 2026-08-14: *"the dfi work wasn't needed
until I was close to doing those controllers."*

Everything below was shaped and ready to start, and was previously
filed as `open`, which overstated its priority — `open` means someone
could sensibly start it today, and for this programme that is not true.
None of it is blocked on effort or on an unknown; it is blocked on
having a consumer. Re-open the individual blocks when one exists.

The CA-map stack it builds on is complete and green
([[DFI-001]]…[[DFI-006]] in [closed.md](closed.md)), so this is
paused at a coherent point rather than mid-change.

Suggested order when it restarts: DFI-007 (the monitor half of the
CA wiring — currently a monitor on any CA-bus DUT reports every
command as NOP, which is the one item with a real correctness edge),
then DFI-011 → 012 → 013, then DFI-014 → 017, then the rest.

## DFI-008 — `dram_state` v6.0 semantics
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above)

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
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); consistency win, no behaviour change intended

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

## DFI-011 — Wire `FlexRandomizer` into `DFIMasterMC` (was D1)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S, no deps

DFI has zero randomization anywhere today. Add an optional `randomizer`
kwarg mirroring `gaxi_master.py` (which drives delays via
`randomizer.next()`), and replace fixed `nop(cycles)` gaps between
commands with randomizer-driven delays.
**Acceptance:** constrained-random command spacing that `DramStateModel`
polices; existing deterministic tests unaffected when no randomizer is
passed.

## DFI-012 — Adopt the shared statistics classes (was D2)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S, no deps

`DFISlavePHY` / `DFIMonitor` / `DFIMasterMC` use manual integer counters
(`writes_committed`, `reads_served`, `command_count`, …). Replace with
`MasterStatistics` / `MonitorStatistics` (`shared/master_statistics.py`,
`monitor_statistics.py`) and `record_*` calls, keeping the DRAM-specific
counters as extra fields.
**Resolve while migrating:** `reads_served` means different things on the
strict and free-running read paths (audit finding).

## DFI-013 — Add `dfi_factories.py` (was D3)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S, no deps

No factory module exists. Add `create_dfi_master`, `create_dfi_slave_phy`,
`create_dfi_monitor`, `create_dfi_scoreboard`, and
`create_dfi_components(dut, clock, …)` mirroring `gaxi_factories.py`. Pure
assembly, low risk, large usability win.
**Note the audit lesson:** the other families' factories shipped broken
because nothing tested them — add unit tests that actually call each one.
A factory is also the natural place to accept a `ca_map` ([[DFI-005]]).

## DFI-014 — Rebase DFI packets on the shared `Packet` (was D4)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort M

DFI packet types are standalone rather than built on the shared `Packet` /
`FieldConfig` machinery, so they miss the formatting, comparison, and
randomization the other families get for free. Unblocks DFI-015 and 016.

## DFI-015 — `DFISequence` DRAM-aware workload generator (was D5)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort M, depends on DFI-011, DFI-014

A sequence layer that generates DRAM-aware traffic (page hit/miss mixes,
bank interleave, refresh pressure) rather than hand-written command lists.

## DFI-016 — Fold `DFIScoreboard` onto `BaseScoreboard` + transformer (was D6)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort M, depends on DFI-014

## DFI-017 — `DFIRandomizationConfig` profiles (was D7)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort M, depends on DFI-011, DFI-013

Named profiles (stress, light, page-thrash) rather than ad-hoc constraints.

## DFI-018 — Signal auto-discovery via `SignalResolver` (was D8)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort M/L

DFI wires signals by explicit name; every other family resolves them.
Note this interacts with the v6.0 `dfi_address` → `dfi_cmdaddr` rename,
which the CA path currently handles with a two-name fallback
(`_ca_bus_word`) that a resolver should subsume.

## DFI-019 — DFI handshake protocol-assertion checker (was D9)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S

## DFI-020 — Coverage hooks + wavedrom binding (was D10)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S, depends on DFI-013

## DFI-021 — Docs build-out: per-class pages + index (was D11)
**Status:** deferred 2026-08-14 (raised 2026-08-13) — parked with the DFI programme (see note above); raised 2026-07 — effort S/M, depends on DFI-011…017

Should now also cover the CA-map stack: how to write a device map, what
`camap_from_dict` expects, and the streaming/dispatch split.
