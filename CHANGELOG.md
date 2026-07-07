# Changelog

## [Unreleased]

## [0.5.0] - 2026-07-07

DFI slave BFM: rdphase/wrphase-aware command decode + physical device-word DRAM
column modeling. These let `DFISlavePHY` faithfully model narrow-device (x16)
DRAM and catch a class of controller column/burst bugs a single-granularity
model was blind to — the bugs behind the on-silicon pumice DDR2 read failure on
the Nexys A7 (fixed controller-side; see RTLDesignSherpa). Backward-compatible:
defaults reduce to the prior behavior.

### Added

- **`DFISlavePHY` physical device-word column model** (issue #31). New
  `dfi_phase_bytes` constructor arg decouples the **DFI phase width** (bus
  slicing, `DFI_RATE`, `rddata_valid` width) from the **device word** (memory +
  column granularity = `memory.bytes_per_line`). `words_per_beat` K =
  `bytes_per_beat / device_bytes` device words pack into each DFI phase.
  `_serve_reads` packs `rddata_bits/dev_bits` device words with `rddata_valid`
  set per DFI phase (`w // K`) so its width stays `DFI_RATE`;
  `_serve_writes_strict` slices per device word; `_handle_command` groups beats
  by `k // (DFI_RATE*K)`; the strict `rddata_en` path returns `DFI_RATE*K` device
  words per asserted cycle. A per-command DRAM-BL device-word column footprint
  then collides when the controller's column stride < BL, so the model
  reproduces the on-silicon x16 write-column overlap. Default
  `dfi_phase_bytes = memory.bytes_per_line` (K=1) is bit-identical to before.
- **`DFISlavePHY` strict write-timing mode** (`strict_write_timing`,
  `write_latency`). Samples `dfi_wrdata` off the wire at exactly
  `command_cycle + write_latency` (faithful DQ-window capture) instead of
  FIFO-committing on any `wrdata_en` — so a controller that presents wrdata late
  fails the read-back, as real DRAM would. Off by default (lenient).
- **`DFISlavePHY` strict read-timing mode** (`strict_read_timing`,
  `read_latency`). Returns `rddata`/`rddata_valid` exactly `read_latency` cycles
  after the controller asserts `dfi_rddata_en` (rddata_en-gated, FIFO-ordered),
  rather than self-timed off CL. Off by default.
- **`raise_on_error` on the AXI4 sequence runners** (`run_axi4_sequence` and the
  engine runner) — turn a sequence mismatch into a hard failure instead of a
  logged warning.

### Fixed

- **`DFISlavePHY` phase-0-only command decode** (issue #30). The decode gate
  tested only phase-0 `cs_n` (`& 1`), silently dropping commands a controller
  places on an upper DFI phase to match a PHY's rdphase/wrphase. Now gates on
  the chip being selected on any phase and decodes ras/cas/we + bank/addr from
  the selected phase (`_active_phase()`); phase-0 traffic unchanged.
- **`dfi_slave_phy` auto-precharge** now actually applied instead of only
  debug-logged.

## [0.4.1] - 2026-07-02

Performance fix release.

### Fixed

- **`MemoryModel.read` O(length × size) → O(length)** (issue #26). `read()`
  evaluated a loop-invariant `np.all(preset_values == 0)` inside its per-byte
  loop, re-scanning the entire memory-sized `preset_values` array on every byte
  of every read. Since BFM slaves call `read()` per beat and `length =
  data_width/8`, wall-time blew up super-linearly with bus width. The all-zero
  test is now cached once (`_preset_all_zero`, recomputed in `expand()`) and the
  per-byte loop is vectorized; stats/warning behavior is unchanged. Impact:
  `stream_core` dw512 config 2h28m→9.28s; DDR2 core-macro `depth_n128`
  >400s (timeout)→9.82s. Speeds up every test using `MemoryModel`, most on wide
  buses.

## [0.4.0] - 2026-06-30

Bug-fix + small-feature release building on 0.3.0. Adds an
engine-faithful pipelined AXI4 sequence runner, fixes a W-beat drop
in `AXI4SlaveWrite` under stall, corrects DFI `DFI_RATE>1` beat
packing on both read and write paths, and adds a single-field
`get_delay()` convenience wrapper to `FlexRandomizer`.

### Added

- **`run_axi4_sequence_engine`** — engine-faithful pipelined runner for
  `AXI4Sequence` (issue #24). Where the existing `run_axi4_sequence`
  drives bursts serially, the new runner mirrors the engine's
  behavior: multiple outstanding transactions in flight, AR/AW
  pipelined ahead of R/B completions, per-burst tracking so ordering
  and burst boundaries stay observable to the scoreboard. Same
  authoring surface (`AXI4Burst` / `AXI4Sequence`) — swap the runner
  to switch modes.
- **`FlexRandomizer.get_delay(field)`** — single-field convenience
  wrapper that returns just the resolved delay for one named field
  without materializing the full randomization dict. Cuts boilerplate
  in call-sites that only need one value.

### Fixed

- **`AXI4SlaveWrite` drops W beats under stall (issue #23).** When the
  pending-write list only contained entries in the
  complete-pending-cleanup state, the W-channel callback took a fast
  return path that discarded incoming W beats instead of buffering
  them against the next AW. Under bursty writer traffic with slow
  scoreboard drain, this manifested as truncated bursts and CRC
  mismatches downstream. Callback now defers cleanup until after any
  in-flight W beats are queued against their AW.
- **DFI `DFI_RATE>1` beat packing on both directions (issue #22).**
  Follow-on to the G-01a decode fix in 0.3.0: reads and writes on
  `DFI_RATE>1` buses now pack the correct number of DRAM beats per
  DFI cycle instead of committing a single beat per cycle. Multi-beat
  AXI bursts through the LPDDR2/3 controller no longer return
  trailing `0x0`. Regression test pins the per-phase pack/slice
  contract for both directions.

## [0.3.0] - 2026-06-23

This release lands the DDR PHY Interface (DFI) BFM for spec versions
2.1 through 5.x — the per-version Strategy + Registry behavior
architecture, all eight semantic-shift areas plumbed end-to-end against
a SystemVerilog wire shim, and the JEDEC timing/state infrastructure
the slave-side BFM uses to model DRAM behavior. The design pressure-
test that preceded the implementation lives in
`docs/internal/dfi-semantic-shifts.md`; the architecture is documented
in commit messages as it landed.

It also lands the LPDDR2/3 CA-bus encoding for both BFM sides, the
LiteDRAM ↔ DFI BFM co-sim end-to-end (with sampler + phase adapter
unit-tested under issue #16), an AXI4 directed-random sequence
authoring layer (issue #20), and a critical `DFISlavePHY`
`DFI_RATE>1` fix that pre-0.3.0 silently dropped every multi-phase
command on the bus (issue #21).

### Fixed — DFISlavePHY DFI_RATE>1 decode (issue #21)

**Critical bug.** Pre-0.3.0 the slave-side BFM gated decode on
`_v(cs_n) == 0`, which is only true when *all* phases are selected.
For typical single-cmd-per-cycle traffic at `DFI_RATE=2` the bus has
`cs_n = 2'b10 = 2` and the decode never ran. The downstream
`_decode_command` further looked up `ras_n / cas_n / we_n` as full
integers (e.g. `2'b11 = 3`) against single-bit decode keys, so even
when decode *did* run every real command silently mapped to NOP. On
top of that, `_serve_writes` read the whole multi-phase wrdata bus as
one beat and overflowed `bytes_per_beat` on commit.

Net effect: any MC driving the bus at `DFI_RATE>1` saw the BFM
appear idle. Writes "succeeded" upstream because the MC's internal
`b_complete` fires independent of any PHY ack, but the BFM memory
model never saw the data. Fresh reads hung indefinitely.

Commits **f8045d7** + **199835f**:

- `cs_n` gate is now `(cs_n & 1) == 0` (phase-0 select).
- `_decode_command` masks each control signal to its LSB before the
  lookup.
- `_serve_writes` walks `wrdata_en` LSB→MSB, popping one pending
  write per active phase, slicing the per-phase data/mask out of the
  packed bus.
- Refactored the two masking concerns into pure helpers
  `decode_phase0_cmd(ras_n, cas_n, we_n)` and
  `slice_phase_wrdata(full_wrdata, full_mask, wrdata_en_bits,
  beat_bytes)` so they can be unit-tested independently.
- Added `tests/unit/test_dfi_slave_phase_masking.py` — 17 unit tests
  covering `DFI_RATE=1` (sanity) and `DFI_RATE=2/4` (regression). Any
  future revert of the masking is caught at unit level, not at the
  consumer.

`tests/unit/` went from 469 → 486 passing.

### Added — AXI4Sequence + run_axi4_sequence (issue #20)

`src/CocoTBFramework/components/axi4/axi4_sequence.py` — a deferred-
execution authoring layer above `AXI4MasterWrite` / `AXI4MasterRead`.
Author canned sequences once (e.g. "random base, then row-hit
follow-ons" or "spray across all banks") in an include module; tests
then pick among them with `FlexRandomizer` and exclude broken ones
until bugs are fixed.

Design philosophy mirrors `GAXISequence`:

- The sequence is **data**, not coroutines. Each entry is an
  `AXI4Burst` describing one bus transaction.
- Execution is a single async function `run_axi4_sequence(seq, ...)`
  that walks the list. Sequences can be regenerated, shuffled, or
  composed without re-authoring the runner.

DDR/SDRAM-aware helpers built in:

- `add_row_hit_burst` — random base then N follow-on column
  increments inside the same row.
- `add_bank_spray` — N bursts across N banks at the same row.
- `add_row_miss_pair` — back-to-back bursts to the same bank but
  different rows (forces PRE→ACT).
- `add_random_workload` — RNG-driven mix using configurable
  W:R / size distributions (the standard "60/40 with
  128B/256B/512B/1024B at 20/20/40/20" pattern).

Cleanup commits along the way:
- **ed3234d** surface write failures; workload alignment + gen_data
  stride fix.
- **efb52a5** 4KB-safe random bursts; fail-fast on missing master.
- **54803a8** MEDIUM/LOW review-item cleanups.
- **3b89324** `docs/AXI4_SEQUENCES.md`.
- **444ac55** + **0491b69** unit tests for builders + runner +
  MEDIUM/LOW coverage.

### Added — LPDDR2/3 CA-bus encoding (commit 20fb5fc)

Both BFM sides (master + slave) now encode and decode the LPDDR2/3
command-address bus per JESD209-2/3 Table 35 + 36. Driven by the
`memory_type` selector on `DFIBase`; the existing DDR2/3/4 path is
unchanged.

### Added — LiteDRAM ↔ DFI BFM co-sim (issue #16)

Real LiteDRAM-emitted DFI traffic now flows through the BFM end-to-
end. Validated across SDR / DDR2 / DDR4 at every supported gear ratio
(commit **db8e20a**), with a dual-clock co-sim harness (commit
**7ace9f3**) where `phy_clk = 4 * mc_clk` for the 1:4 gear. Slave
wrdata FIFO matching fix in **1edb8b5**. Medium-stress soak (full
command coverage on all 4 phases) in **b191cc4**. Cross-validation
of DFI version envelopes v3.1 through v5.2 in **fdef730**.

### Added — DFI BFM (issue #16)

**Core infrastructure** — `src/CocoTBFramework/components/dfi/`

- `dfi_signals.py` — signal envelope for v2.1-v5.x. Encodes 30+
  `SignalSpec` entries with per-spec-revision `min_version` /
  `max_version` and per-memory-type gating. `SUPPORTED_MEMORY_BY_VERSION`
  matrix maps each version to its applicable memory types (DDR1-5,
  LPDDR1-5). `MVP_VERSIONS` / `MVP_MEMORY_TYPES` / `MVP_SUB_INTERFACES`
  define the envelope `validate_configuration()` enforces at BFM init.

- `dfi_base.py` — `DFIBase` chassis. Holds the JEDEC timings,
  `AddressMapping`, sub-interface selection, and the per-version
  `behavior` instance. Validates `(dfi_version, memory_type)` against
  the spec at construction. `beats_per_burst` parameter handles DDR3
  BL=8 with K=2 PHY ratio (4 DFI beats per burst); overridable.

- `dfi_master_mc.py` — `DFIMasterMC` cocotb_bus.BusDriver subclass.
  Primitive API: `activate`, `read`, `write`, `write_data`,
  `write_burst`, `precharge`, `refresh`, `nop`. Plus area-specific
  drivers: `set_ctrlupd_req`, `set_phyupd_ack`, `set_parity_in`,
  `set_freq_change`, `set_disconnect_ack`, `set_phymstr_ack`.

- `dfi_slave_phy.py` — `DFISlavePHY` cocotb_bus.BusMonitor subclass.
  Auto-commits writes after CWL, serves reads CL cycles after RD
  commands, queues reads behind in-flight writes (queue-don't-collide
  semantics). Owns `DramStateModel` for per-bank state + JEDEC timing
  enforcement, and `MemoryModel` for numpy-backed storage. Drives
  PHY-side signals via `set_error`, `set_crc_alert`, `set_phyupd_req`,
  `set_ctrlupd_ack`, `set_training`, `set_parity_check`,
  `set_freq_change_ack`, `set_disconnect_req`, `set_phymstr_req`.

- `dfi_monitor.py` — passive `DFIMonitor` with `side="mc"` /
  `side="phy"` parameter. Per-sub-interface capture queues
  (`command_q`, `write_data_q`, `read_data_q`) populated each cycle.

- `dfi_packet.py` — `DFIControlPacket`, `DFIWriteDataPacket`,
  `DFIReadDataPacket` dataclasses. `DRAMCommand` enum + DDR3 (ras_n,
  cas_n, we_n) encoding table. `DFIControlPacket.from_command()`
  builder handles auto_precharge / all_banks via addr[10].

- `dfi_field_configs.py` — `command_field_config`,
  `write_data_field_config`, `read_data_field_config` builders.

**JEDEC + DRAM modeling** — `src/CocoTBFramework/components/dfi/`

- `jedec_timings.py` — `JedecTimings` dataclass + CSV loader.
  Converts ns values to cycles using ceil at the configured tCK.
  Forward-compatible: unknown parameters preserved in `.extras`.

- `jedec/ddr3-1600.csv` — DDR3-1600 reference (Micron MT41J512M8
  timings, JESD79-3F).

- `jedec/ddr2-650-mt47h64m16hr.csv` — DDR2-650 reference for the
  Micron MT47H64M16HR-25:H part used on Digilent FPGA boards. This
  is the planned first hard-test target once the MC RTL lands.

- `dram_state.py` — `DramStateModel` (per-bank state machine + 8 hard
  JEDEC timing checks + tFAW soft check), `Bank` dataclass, `BankState`
  enum, `ViolationPolicy` with configurable hard/soft/ignore
  categorization. `AddressMapping` for late-binding flat ↔
  (rank, bank, row, col) decode — `row|bank|col` default, configurable
  ordering string supports `row|col|bank` etc. Pattern mirrors
  DRAMsim3's `SetAddressMapping`; the alternative wired-in slicing
  (LiteDRAM's pattern) was deliberately rejected.

**Per-version behavior classes** — `src/CocoTBFramework/components/dfi/behaviors/`

- Strategy + Registry pattern. One method per semantic-shift area
  on the base class; subclasses override areas that change in their
  version. The `VERSION_BEHAVIOR` dict in `registry.py` is the only
  place that maps `DFIVersion` to a behavior class. Adding a new DFI
  revision is one row in the dict.

  - `base.py` — `DFIv2_1Behavior`. All post-v2.1 areas raise
    `NotSupportedInThisVersionError` (subclass of `NotImplementedError`).
    Basic frequency-change sampling (the one v2.1-native area).
  - `v3_1.py` — `DFIv3_1Behavior`. Implements `crc`, `update_request`,
    `update_grant`, `training_step`, `error_event`, `ca_parity_check`
    (v3.0 introductions) plus the v3.1 PHY-requested training mode
    (encoded as `TrainingPhase.PHY_REQUESTED`).
  - `v4_0.py` — `DFIv4_0Behavior`. Implements `phy_takeover`,
    `phy_release`, `disconnect_request`, `disconnect_release` (v4.0
    introductions), plus the v4.0 Ack/Not-Ack `freq_change` split via
    `FreqChangeProtocol` enum decode. Inherits everything else from
    v3.1.
  - `registry.py` — `VERSION_BEHAVIOR` dict + `behavior_for(version)`
    helper. V2_1 → base; V3_1 → v3.1; V4_0 → v4.0; V5_2 → v4.0
    (PHY-Master rename has no behavior implication per the catalog).
    Unknown versions raise loudly at construction.
  - `events.py` — eight frozen dataclasses, one per shift area:
    `CRCEvent`, `UpdateEvent`, `TakeoverEvent`, `DisconnectEvent`,
    `FreqChangeEvent`, `TrainingEvent`, `ErrorEvent`, `CAParityEvent`.
    Pattern-matchable types; enum fields carry kind/phase/protocol/
    state distinctions.
  - `exceptions.py` — `NotSupportedInThisVersionError` with
    machine-readable `(area, version, introduced_in)` fields.

**Custom behavior override**: `DFIBase(behavior=MyCustomV4Behavior())`
bypasses the registry; lets users model board-specific PHY quirks.

**Eight semantic-shift areas, end-to-end plumbed**

Each area added: SignalSpec entries, shim wires, per-area Event
type/enum, slave queue + `_dispatch_behavior_X` helper, master or
slave drive primitives, behavior method implementation, Tier 1 unit
tests, and a Tier 2 cocotb proof test:

- **Error interface** — `dfi_error` + `dfi_error_info`; v3.0+
- **CRC handshake** — `dfi_crc_alert` (active high; mirrors DDR4
  ALERT_n); v3.0+ DDR4
- **Update interface** — `dfi_ctrlupd_req/ack` (v2.1+) and
  `dfi_phyupd_req/ack` (v3.0+). MC-initiated wins when both asserted
  same cycle.
- **Training interface** — `dfi_training_active` + 3-bit
  `dfi_training_phase`. Single-method shape validated after the
  LiteDRAM survey (catalog section 6 risk retired): training is
  parallel hardware under software sequencing; phase distinction is
  data on `TrainingEvent.phase`, not separate methods. Covers
  read/write/DQ/CA/DB leveling phases.
- **CA parity** — `dfi_parity_in` + `dfi_parity_check`; v3.0+ DDR4
- **Frequency change** — `dfi_freq_change_req/ack` (v2.1+) +
  `dfi_freq_change_protocol` (v4.0+; 2-bit Basic/Ack/NotAck variant).
  First multi-version implementation: v2.1 base emits BASIC; v4.0
  override decodes protocol field.
- **Disconnect Protocol** — `dfi_disconnect_req/ack`; v4.0+ only
- **PHY Master/Managed Interface** — `dfi_phymstr_req/ack`; v4.0+ only

### Added — SystemVerilog wire shim

- `tests/sim/rtl/dfi/dfi_shim.sv` — pure-passthrough shim with all
  29 DFI signals exposed on both MC- and PHY-facing ports. Lets two
  monitors (or master + slave) verify the same packet stream lands on
  both sides without simulating actual logic between them. Parameters:
  `ADDR_WIDTH`, `BANK_WIDTH`, `CS_WIDTH`, `CTRL_WIDTH`, `DATA_WIDTH`,
  `DATA_EN_WIDTH`, `DATA_MASK_BITS`, `RD_VALID_WIDTH`,
  `ERROR_INFO_WIDTH`, `TRAINING_PHASE_WIDTH`.

### Added — Tests

- **104 new Tier 1 unit tests** covering signal-envelope validation,
  packet builders, field configs, JEDEC CSV loader, ViolationPolicy,
  DramStateModel (incl. tFAW windowing), AddressMapping (geometry
  parsing, bit-slice ordering, round-trip), DFIBase configuration
  + behavior selection + custom override, all 11 behavior methods on
  all three behavior classes, all 8 Event dataclass shapes.

- **11 new Tier 2 cocotb sim tests** (in 10 distinct sim builds):
  dual-monitor round-trip, master primitive sequence, end-to-end
  write/read loopback, BL=8 burst, and 7 proof-of-life tests covering
  every semantic-shift area against the wire shim through verilator.

### Documentation

- `docs/internal/dfi-semantic-shifts.md` — design catalog of every
  shift area, written before any code, used as the pressure-test for
  the per-version-class architecture. Section 6's open question on the
  training method shape was retired by the LiteDRAM survey + the
  implementation that landed.

### Changed

- **`SUPPORTED_MEMORY_BY_VERSION` scoped to v2.1-v5.x.** v6.0 dropped
  DDR1-4 + LPDDR1-4 — that's a sufficient discontinuity to be a future
  BFM generation, not an extension of this one. v6.0 / LPDDR6 / HBM4
  removed from the active scope; research preserved in the memory note.

- **`MVP_VERSIONS` widened to {V2_1, V3_1}** and **`MVP_MEMORY_TYPES`
  widened to include DDR4** — needed for the v3.0 error/CRC/CA-parity
  proofs. Phase 2 will further widen for v4.0/v5.2.

### Reference (cloned alongside this repo, not in-repo)

- LiteDRAM at `../mem-ctrl-ref/litedram/` — open-source DDR1-4 + LPDDR4
  controller in Python+Migen. Reference for the per-bank state machine
  pattern, refresh scheduling, vendor PHY shim layering. Does **not**
  implement DFI v3.0+ training signals (uses CSR-only training instead).
- DRAMsim3 at `../mem-ctrl-ref/DRAMsim3/` — UMD DRAM simulator with 60+
  JEDEC chip configs. Reference for the late-binding `AddressMapping`
  pattern we adopted (vs LiteDRAM's wired-in slicing).

### Tests

- **Tier 1**: 359 unit tests pass in <1 second
- **Tier 2**: 11 cocotb sim tests pass across 10 verilator builds
  in ~7 seconds fresh / <2 seconds cached

## [0.2.0] - 2026-06-09

This release lands the methodology-review followups (#6–#15) plus a
substantial test-infrastructure rollup that wasn't tracked by its own
issues — see the **Test infrastructure** section at the bottom for what
was rolled in alongside the issue-tracked work. The BFM source-of-truth
changes are the issue-tracked items; the infrastructure rollup gives
the DV repo a regression that can validate those changes (and future
ones) without depending on the RDS \`val/\` suite.

### Breaking changes (BFM API)

The breaking-change details are documented inline in each entry below;
high-level summary for downstream migration:

- **APB5Master.send()** now returns after queueing instead of after the
  bus transaction completes. Use \`busy_send()\` for completion semantics.
  (#15 Phase A — matches what APB4 callers already had.)
- **APB5Slave** \`ready_delay\` is now measured from PSEL detection (was
  PENABLE rising). Observable 1-cycle timing difference for cycle-precise
  testbenches. (#15 Phase B)
- **APBSlave** now dispatches monitor transactions via \`self._recv()\` —
  TBs that asserted \`_recvQ\` was empty will see packets now. Strictly
  additive — most consumers benefit.
- MRO changes: \`isinstance(x, APBMaster)\` now matches APB5 masters;
  \`isinstance(x, GAXIComponentBase)\` now matches FIFO BFMs; etc. All
  document'd per-entry below.

### Changed

- **Type annotations on GAXI/FIFO base-class signatures.** Added full
  type annotations to the `__init__` signatures and public methods of
  the ready/valid component bases: `GAXIComponentBase`, `GAXIMonitorBase`,
  `FIFOComponentBase`, `GAXIMaster`, `GAXISlave`, `GAXIMonitor`.
  Introduced `DutHandle = Any` / `ClockSignal = Any` /
  `FieldConfigInput = Union[FieldConfig, dict, None]` type aliases in
  `gaxi_component_base.py` and re-exported them from the modules that
  consume them. Cocotb handle types are kept as `Any` because their
  concrete types vary by simulator backend. No runtime behavior change;
  IDEs and type checkers can now assist downstream BFM authors.
  ([#11](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/11))

- **APB5 inherits from APB (Monitor + Master + Slave).** Refactored
  `APBMonitor`, `APBMaster`, and `APBSlave` to expose extension hooks;
  `APB5Monitor`, `APB5Master`, and `APB5Slave` now inherit from them.
  Eliminates the parallel `_monitor_recv` edge-detection loops and the
  parallel signal-init boilerplate.
  ([#15](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/15))

  Hooks added to `APBMonitor`:
  - `_build_packet(...)` — APB5Monitor overrides to return an `APB5Packet`
    with USER/WAKEUP fields populated.

  Hooks added to `APBMaster`:
  - `_default_randomizer_constraints()`
  - `_init_extension_signals()`
  - `_drive_extension_setup_phase(transaction)`
  - `_capture_extension_response(transaction)`

  Hooks added to `APBSlave`:
  - `_default_randomizer_constraints()`
  - `_init_extension_signals()`
  - `_capture_extension_input_fields()`
  - `_drive_extension_response(rand_values)`
  - `_build_packet(...)`

  **APB5Master gains parity with APB4Master**: previously had no
  `transmit_queue`, no `_transmit_pipeline`, no `FlexRandomizer` for
  PSEL/PENABLE delays, no `busy_send` / `reset_bus`. All of these are
  inherited now. The previous direct-drive `_driver_send` is replaced by
  the inherited queued pipeline. APB5Master's `write()` / `read()`
  convenience methods now route through `busy_send`.

  **APB5Slave fixes two latent bugs** that the empty test suite hadn't
  caught: `self.mem.write(line, wdata, strb)` previously passed an int
  for `wdata` and a line index for the address (MemoryModel.write
  requires a byte address and a bytearray — would have raised TypeError);
  `self.mem.read(line)` was missing the required `length` argument. The
  unified flow uses the correct byte-address + bytearray API.

  **Observable APB5 behavior changes:** `ready_delay` is now measured
  from PSEL detection (1 cycle earlier than the old PENABLE-rising
  baseline); memory overflow now auto-expands by default (was previously
  silent failure when `error_overflow=False`); APBSlave now dispatches
  via `self._recv()` (APB5 already did — APB4 picks it up for free).

  Public class names preserved (`APB5Monitor`, `APB5Master`, `APB5Slave`).

  **Breaking change risk (moderate):** users subclassing `APB5Master` /
  `APB5Slave` directly will see MRO changes. `APB5Master.send()`
  previously drove the bus synchronously; now it queues (matches APB4's
  behavior — use `busy_send()` to wait for completion).
  `isinstance(x, APBMaster)` and `isinstance(x, APBSlave)` on APB5
  instances now return True.

- **Shared APB/APB5 constants.** Added
  `components/shared/apb_common.py` with `BASE_APB_SIGNALS`,
  `BASE_APB_OPTIONAL_SIGNALS`, and `PWRITE_DIR`. Both
  `apb/apb_components.py` and `apb5/apb5_components.py` now import these
  rather than re-defining them. APB5's optional-signals list is now
  explicitly expressed as the APB4 set plus an `_APB5_EXTENSION_OPTIONAL_SIGNALS`
  delta. Public module-level names (`apb_signals`, `apb_optional_signals`,
  `apb5_signals`, `apb5_optional_signals`, `pwrite`) preserved.
  ([#8](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/8),
  superseded by [#15](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/15)
  which does the full structural extraction via inheritance hooks.)

- **AXISSlave now inherits GAXISlave (was GAXIMonitorBase).** AXIS is a
  ready/valid protocol like every other GAXI consumer; the previous
  inheritance skipped the structured pipeline state machine, the
  `pipeline_debug` plumbing, and `_set_ready` from `GAXISlave`, and
  reimplemented `_monitor_recv` on top of the bare monitor base. Now
  inherits `GAXISlave`; the AXIS `_monitor_recv` override is preserved
  for TLAST/frame tracking. `AXIS5Slave` picks up the change transitively
  (it inherits `AXISSlave`).

  Also fixed two latent bugs in the same constructor:
  - Duplicate `complete_base_initialization()` call (super already calls it).
  - `randomizer`, `memory_model`, and `pipeline_debug` were stored as
    attributes *after* `super().__init__()` instead of being forwarded —
    meaning the base never received them. Now forwarded properly.

  ([#7](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/7))

  **Breaking change risk (low):** users doing `isinstance(x, GAXIMonitorBase)`
  on an AXIS slave still match transitively. Users subclassing `AXISSlave`
  and overriding init may need to review forwarding.

- **Canonical `protocol_type` set.** Added
  `components/shared/protocol_types.py` providing `PROTOCOL_TYPES`
  (frozenset) and `validate_protocol_type()`. `GAXIComponentBase` and
  `FIFOComponentBase` now validate against this single source of truth
  instead of carrying their own hard-coded lists. Adding a new channel
  type now requires editing one file. No public API change.
  ([#9](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/9))

- **Framework kwarg stripping helper.** Added
  `components/shared/init_kwargs.py` with `FRAMEWORK_KWARGS` canonical
  tuple and `strip_framework_kwargs()` / `pop_framework_kwargs()` helpers.
  `GAXIMaster.__init__` and `GAXIMonitorBase.__init__` now call the helper
  instead of open-coding the `for param in custom_params: kwargs.pop(...)`
  dance. Adding a new framework kwarg now requires updating one tuple.
  ([#10](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/10))

- **`GAXIComponentBase` is now the canonical ready/valid component chassis.**
  `FIFOComponentBase` is a deprecated thin alias for `GAXIComponentBase`.
  `GAXIComponentBase` now accepts `fifo_master` / `fifo_slave` as
  `protocol_type` values and supplies the matching `write_delay` /
  `read_delay` randomizer defaults. Previously the FIFO and GAXI bases
  were ~95% duplicates that drifted independently. Existing imports of
  `FIFOComponentBase` continue to work; `FIFOMaster` / `FIFOSlave` /
  `FIFOMonitor` retain their `FIFOComponentBase` base class. A future
  release will switch the FIFO BFMs to inherit `GAXIComponentBase`
  directly and remove the shim.
  ([#6](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/6))

  **Breaking change risk (low):** users doing
  `isinstance(x, GAXIComponentBase)` on a FIFO BFM now match (correctly).
  Users subclassing `FIFOComponentBase` directly continue to work.

### Documentation

- **AXI4SlaveRead in-order serialization synchronization assumption.** Audited
  `_generate_read_response_serialized` and `_ar_callback` for the race class
  that previously affected `completion_locks` (PR for #5 / commit `9d6cbc9`).
  No race exists: all mutations of `in_order_active` / `in_order_queue` happen
  between awaits within the coroutine, and cocotb's cooperative scheduler keeps
  them atomic. Added an explicit synchronization note in the docstring and
  inline comments so a future maintainer doesn't introduce an across-await
  hazard. No code behavior change.
  ([#13](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/13))

- **AXI4SlaveWrite AW/W callback synchronization invariant.** Audited
  `_aw_callback`, `_w_callback`, `_match_orphaned_w_packets`, and
  `_complete_write_transaction` for races on `pending_transactions`,
  `orphaned_w_packets`, and `w_transaction_queue`. No race exists: callbacks
  are sync `def`s (cannot await), `_complete_write_transaction`'s critical
  section is guarded by the per-ID `completion_locks`, and the `finally`
  cleanup uses `list.remove` (atomic between awaits). Added a synchronization
  invariant block in `__init__` and "MUST remain sync" notices on each
  callback's docstring so a future maintainer doesn't introduce an
  across-await hazard by converting them to `async def`. No code behavior
  change.
  ([#14](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/14))

- **BFM class conventions.** Added a "BFM Class Conventions" section to
  `docs/components/components_overview.md` explaining the Slave-via-BusMonitor
  pattern (every Slave BFM inherits `cocotb_bus.BusMonitor` even though it
  drives response signals — `cocotb_bus` has no "responder" base class, so
  `BusMonitor` is reused as a chassis). Added docstring pointers to
  `APBSlave`, `APB5Slave`, and `GAXISlave` so the convention is discoverable
  from the source.
  ([#12](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/12))

### Test infrastructure (not tracked by individual issues — rolled in)

The following work landed alongside the issue-tracked refactors to give
the DV repo a regression that can validate the BFM changes (and future
ones) without depending on the RDS `val/` suite. It wasn't filed as
individual issues; documented here for visibility.

- **Tier 1 pytest suite** (`tests/unit/`) — 123 tests, runs in <1s, no
  simulator required. Covers `MemoryModel` API contract, `protocol_types`
  (#9), `init_kwargs` (#10), `apb_common` (#8), `FieldConfig`,
  `FlexRandomizer`, packet construction, inheritance hooks (#15), and
  inheritance structure (#6, #7, #15). **Found and fixed a real bug**:
  `APBMaster._default_randomizer_constraints` was returning `[0, 0]`
  (list) bin pairs instead of `(0, 0)` (tuples), which `FlexRandomizer`
  rejects. Pre-existed #15. Now fixed and guarded by regression test.

- **Tier 2 sim test scaffolding** (`tests/sim/`) — `conftest.py` with
  prerequisite detection (skips cleanly when `cocotb-test` or a Verilog
  simulator is missing, so unit tests still run on bare metal); vendored
  snapshot of RDS `bin/TBClasses/` at commit `7aee11af` under
  `tests/sim/TBClasses/` so `from TBClasses.shared.tbbase import TBBase`
  works without an RDS submodule; curated RTL snapshot under
  `tests/sim/rtl/` (105 SV files, 3.6 MB) including bridges from
  `projects/components/bridge/`, the APB crossbar, and converters.

- **6 new BFM-stress bridges** — generated via the RDS bridge generator
  from TOML specs in `tests/sim/bridge_specs/`. Each has ≥ 8 ports and
  ≥ 2 masters, covering the full AMBA4 master×slave protocol matrix.
  Bridges: `bridge_a_axi4_widthmix_4x4`, `bridge_b_axi4_axil_3x5`,
  `bridge_c_dma_heavy_3x6`, `bridge_d_axil_emphasis_4x4`,
  `bridge_e_grand_mix_5x5`, `bridge_f_fanout_2x8`.

- **Sophisticated concurrent testbench infrastructure**
  (`tests/sim/bridges/tbclasses/`) — generic TOML-driven `ConcurrentBridgeTB`
  that auto-builds the right BFM topology for any bridge, pre-seeds
  slave MemoryModels with a misroute-detection pattern, and exposes 4
  concurrency-stress helpers (`parallel_storm`, `same_id_storm`,
  `cross_protocol_race`, `read_response_race`). Cross-master scoreboard
  with per-(master, slave) tally and per-`(master, txn_id)` read-response
  matching. 8 concurrent stress tests targeting specific BFM
  synchronization paths from v0.1.1 (#3, #4, #5) and this release (#15).

- **`env_python`** — DV-appropriate environment setup script. Activates
  the venv, puts `src/` and `tests/sim/` on `PYTHONPATH`, auto-detects
  `RDS_RTL_PATH`, exposes test aliases (`ptu` / `pts` / `ptw` / `ptwp` /
  etc.) mirroring RDS's convention. Replaces a copy of RDS's env script
  that had a lot of irrelevant exports.

- **`pyproject.toml [sim]` optional dep group** — `cocotb-test`,
  `pytest-xdist`, `pytest-asyncio`, `pytest-rerunfailures`, `GitPython`,
  `tomli` (Python 3.10 fallback). Install with `pip install -e ".[sim]"`.

- **`TODO.md`** — root-level project tracker linking each open issue to
  its target release and status. Will move to GitHub Projects later.

## [0.1.1] - 2026-06-01

### Fixed

- **AXIL4SlaveRead/Write `base_addr` offset.** Incoming AR/AW addresses are
  absolute (post-decode); the slaves now subtract `base_addr` before
  indexing the memory model. A new `base_addr` kwarg mirrors the existing
  `AXI4SlaveRead/Write` API. Without this fix, slaves at non-zero base
  addresses returned `0xDEADDEAD` or `SLVERR`.
  ([#1](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/1),
  commit [`2e7e825`](https://github.com/sean-galloway/RTLDesignSherpa-DV/commit/2e7e825))

- **AXIL4SlaveWrite AW/W pairing.** Replaced single-depth `pending_aw` /
  `pending_w` slots with `_aw_queue` / `_w_queue` FIFOs so pairs drain
  strictly in arrival order. Fixes silent AW/W mis-pairing under
  interleaved burst patterns from upstream burst-decomposing shims (e.g.
  `axi4_to_axil4_wr`).
  ([#2](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/2),
  commit [`2e7e825`](https://github.com/sean-galloway/RTLDesignSherpa-DV/commit/2e7e825))

- **AXI4/AXI5/AXIL4 master BFM response pickup race.** Each master BFM
  now routes incoming R/B packets through a monitor callback into per-ID
  deques (AXI4/AXI5: keyed on `RID`/`BID`) or a FIFO of waiter slots
  (AXIL4: keyed on issue order). `read_transaction` /
  `write_transaction` pop from their own queue/slot rather than indexing
  into the shared `_recvQ`. Fixes the silent failure where concurrent
  `cocotb.start_soon`-dispatched transactions all received the same
  response packet. Sequential callers see zero behavior change.
  ([#3](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/3),
  commit [`e5ebf7b`](https://github.com/sean-galloway/RTLDesignSherpa-DV/commit/e5ebf7b))

- **AXI4/AXI5/AXIL4 MasterWrite AW+W serialization.** Each master-write
  BFM now wraps `(send AW, send all W beats)` in a
  `cocotb.triggers.Lock`. Concurrent same-ID writes no longer interleave
  W beats on the wire (AXI W has no ID; slaves match by AWLEN/WLAST
  ordering, so interleaving silently delivers each transaction's data
  to the wrong destination). Sequential callers see an uncontended
  lock — zero behavior change.
  ([#4](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/4),
  commit [`e5ebf7b`](https://github.com/sean-galloway/RTLDesignSherpa-DV/commit/e5ebf7b))

- **AXI4/AXI5 SlaveWrite Lock primitive.** Replaced `asyncio.Lock` with
  `cocotb.triggers.Lock` in per-ID `completion_locks`. `asyncio.Lock` is
  unusable under cocotb's scheduler — `get_event_loop()` returns `None`,
  so `acquire()` raises `AttributeError: 'NoneType' object has no
  attribute 'create_future'` on first contention. The bug was latent in
  v0.1.0 because master-side concurrency was effectively blocked by the
  response-pickup race fixed in #3; with that fix in place, the
  slave-side path becomes reachable.
  ([#5](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/5),
  commit [`9d6cbc9`](https://github.com/sean-galloway/RTLDesignSherpa-DV/commit/9d6cbc9))

### Documentation

- MkDocs site live at <https://sean-galloway.github.io/RTLDesignSherpa-DV/>,
  with site logo, favicon, and complete API reference for all protocol
  BFMs.

## [0.1.0] - 2026-03-22

### Added
- Initial extraction from RTLDesignSherpa monorepo
- Protocol BFM components: AXI4, AXI5, AXI4-Lite, APB, APB5, AXI-Stream, FIFO, GAXI, SMBus, UART
- Testbench base classes with TBBase foundation (clock, reset, logging, safety monitoring)
- Transaction verification scoreboards
- Wavedrom waveform visualization utilities
- Flexible randomization framework
- Memory model for complex verification scenarios
- PyPI packaging with `pip install cocotb-framework`
