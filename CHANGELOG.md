# Changelog

## [Unreleased]

### Changed

- **Shared APB/APB5 constants.** Added
  `components/shared/apb_common.py` with `BASE_APB_SIGNALS`,
  `BASE_APB_OPTIONAL_SIGNALS`, and `PWRITE_DIR`. Both
  `apb/apb_components.py` and `apb5/apb5_components.py` now import these
  rather than re-defining them. APB5's optional-signals list is now
  explicitly expressed as the APB4 set plus an `_APB5_EXTENSION_OPTIONAL_SIGNALS`
  delta. Public module-level names (`apb_signals`, `apb_optional_signals`,
  `apb5_signals`, `apb5_optional_signals`, `pwrite`) preserved.
  ([#8](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/8))

  **Scope note:** The original audit estimated APB and APB5 share ~80% of
  code. On closer inspection only the **Monitor** edge-detection loops are
  materially duplicated. `APBMaster` uses a queued, randomized transmit
  pipeline (`_transmit_pipeline` / `_finish_xmit`); `APB5Master` directly
  drives in `_driver_send` with no queue. Slave implementations diverge
  similarly because APB5 carries USER/WAKEUP/parity fields. Extracting a
  shared Master/Slave base would force one style onto the other and is
  declined. A future PR can extract a common `_APBMonitorBase` for the
  edge-detection loop with override hooks for protocol-specific field
  capture; this PR is the seed (the shared module is in place, the
  scope-reduction rationale is captured in `apb_common.py`'s docstring).

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
