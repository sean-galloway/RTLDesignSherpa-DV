# Changelog

## [Unreleased]

### Changed

- **APB5 inherits from APB (Monitor + Master).** Refactored `APBMonitor`
  and `APBMaster` to expose extension hooks; `APB5Monitor` and
  `APB5Master` now inherit from them. Eliminates the parallel
  `_monitor_recv` edge-detection loops and the parallel signal-init
  boilerplate. ([#15](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/15))

  Hooks added to `APBMonitor`:
  - `_build_packet(...)` — constructs the protocol-specific packet from
    sampled bus values. APB5Monitor overrides to return an `APB5Packet`
    with USER/WAKEUP fields populated.

  Hooks added to `APBMaster`:
  - `_default_randomizer_constraints()` — APB4 returns `psel` / `penable`
    defaults; subclasses can add extension-field constraints.
  - `_init_extension_signals()` — APB5Master overrides to zero PAUSER /
    PWUSER at construction.
  - `_drive_extension_setup_phase(transaction)` — APB5Master overrides to
    drive PAUSER / PWUSER during the setup phase of `_finish_xmit`.
  - `_capture_extension_response(transaction)` — APB5Master overrides to
    sample PRUSER / PBUSER / PWAKEUP after PREADY rises.

  **APB5Master gains parity with APB4Master**: previously had no
  `transmit_queue`, no `_transmit_pipeline`, no `FlexRandomizer` for
  PSEL/PENABLE delays, no `busy_send` / `reset_bus`. All of these are
  inherited now. The previous direct-drive `_driver_send` is replaced by
  the inherited queued pipeline. APB5Master's public `write()` / `read()`
  convenience methods now route through `busy_send` so they wait for the
  queued transaction to complete.

  Public class names preserved (`APB5Monitor`, `APB5Master`, `APB5Slave`).

  **Phase B (this PR also).** `APB5Slave` now inherits from `APBSlave` via
  five extension hooks: `_default_randomizer_constraints`,
  `_init_extension_signals`, `_capture_extension_input_fields`,
  `_drive_extension_response`, `_build_packet`. The unified
  `_monitor_recv` state machine lives in `APBSlave`. The merge also
  **fixes two latent bugs** in the old `APB5Slave._monitor_recv` that
  the empty test suite hadn't caught:

  - `self.mem.write(line, wdata, strb)` was passing an integer for
    `wdata` and a line index for the address. `MemoryModel.write`
    requires a *byte address* and a *bytearray*; the call would have
    raised `TypeError` on first execution. The unified flow uses the
    correct byte-address + bytearray API (matches `APBSlave`).
  - `self.mem.read(line)` was missing the required `length` argument.
    Now fixed via the unified flow.

  Additional observable change for APB5: `ready_delay` is now measured
  from PSEL detection (1 cycle earlier than the old PENABLE-rising
  baseline), and memory overflow now auto-expands by default (was
  previously silent failure on overflow when `error_overflow=False`).

  **Breaking change risk (moderate):** users subclassing `APB5Master`
  directly will see MRO changes (`APB5Master` → `APBMaster` → `BusDriver`).
  Users calling `APB5Master.send()` previously got a direct synchronous
  drive; now they get the queued pipeline (which is what APB4 callers
  already had, and is the architectural improvement this PR delivers).
  `isinstance(x, APBMaster)` on an APB5 master now returns True.

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
