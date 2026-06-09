# Changelog

## [Unreleased]

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
