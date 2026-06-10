# Concurrent Bridge Stress Tests

Sophisticated cocotb tests built on top of the generated bridges in
`tests/sim/rtl/bridges/`, designed specifically to stress the
**framework BFMs** under high concurrency rather than to verify bridge
RTL correctness.

## What gets exercised

| Concurrency path | Where it lives | Which test stresses it |
|---|---|---|
| Per-ID R-response demux | `AXI4MasterRead._response_by_id` (v0.1.1 #3) | `bridge_c::per_id_response_race` |
| AW+W serialization lock | `AXI4MasterWrite` AW+W `cocotb.triggers.Lock` (#4) | `bridge_c::parallel_storm`, `bridge_c::same_id_completion_lock` |
| Per-ID B-completion locks | `AXI4SlaveWrite.completion_locks` (#5) | `bridge_c::same_id_completion_lock` |
| AXIL4 base_addr offset | `AXIL4Slave{Read,Write}` (v0.1.1 #1, #2) | `bridge_b::parallel_storm`, `bridge_b::cross_protocol_race` |
| APBSlave unified state machine | `APBSlave._monitor_recv` (#15 Phase B) | `bridge_c::apb_fan_in` |
| APBMaster queued pipeline | `APBMaster._transmit_pipeline` (#15 Phase A, inherited by APB5Master) | `bridge_c::parallel_storm` (APB tail), `bridge_b::cross_protocol_race` |
| Cross-protocol scheduling | All three master-protocol drivers running concurrently | `bridge_b::cross_protocol_race` |

## Layout

```
bridges/
├── tbclasses/
│   ├── concurrent_bridge_tb.py    # Generic TOML-driven TB base
│   └── scoreboard.py              # Cross-master verification
├── test_bridge_b_concurrency.py   # 3 tests for bridge_b
├── test_bridge_c_concurrency.py   # 5 tests for bridge_c
└── README.md
```

## How the generic TB works

`ConcurrentBridgeTB(dut, toml_path=...)`:

1. Parses the bridge's TOML at construction → discovers master/slave
   counts, protocols, widths, base addresses.
2. Auto-instantiates the right BFM per master (AXI4/AXIL/APB) and per
   slave (AXI4/AXIL/APB) using the protocol field from the TOML.
3. Pre-seeds each slave's MemoryModel with a per-slave pattern
   `((slave_idx+1) << 24) | word_offset` so misroutes are visible at hex.
4. Parses the connectivity CSV next to the TOML → `can_route(m, s)`.
5. Exposes high-level helpers:
   - `master_write(m_idx, addr, data, byte_count, txn_id)` —
     protocol-dispatched, registers with scoreboard
   - `master_read(m_idx, addr, byte_count, txn_id)` — same
   - `parallel_storm(per_master_txns, write_fraction)` — every master
     fires N transactions concurrently
   - `same_id_storm(m_idx, s_idx, txn_id, count, operation)` — N
     concurrent transactions same-ID
   - `cross_protocol_race(per_master_txns)` — heterogeneous protocols
     dispatch in the same window
   - `read_response_race(m_idx, s_idx, n_concurrent, ids_in_play)` —
     stresses per-ID R demux
6. `verify_scoreboard()` reads back every slave's MemoryModel and
   compares against registered writes; logs per-master/per-slave
   match counts plus a mismatch list.

## Adding more bridges

Each new bridge needs ~80 lines of test file (one per-test-case +
pytest wrapper). The `ConcurrentBridgeTB` base does all the BFM and
scoreboard wiring; per-bridge tests just instantiate it with the right
TOML path and call the stress helpers.

To add `bridge_e_grand_mix_5x5`:

```python
# tests/sim/bridges/test_bridge_e_concurrency.py
_TOML = str(_HERE.parent / "bridge_specs" / "bridge_e_grand_mix_5x5.toml")

@cocotb.test(timeout_time=500, timeout_unit="ms")
async def cocotb_test_bridge_e_parallel_storm(dut):
    tb = ConcurrentBridgeTB(dut, toml_path=_TOML)
    await tb.setup_clocks_and_reset()
    await tb.parallel_storm(per_master_txns=20)
    await tb.settle()
    assert tb.verify_scoreboard()

# ... pytest wrapper similar to bridge_b/c ...
```

## Prerequisites for actually running

- Verilator on PATH (cocotb default; iverilog is workable but slower)
- `cocotb-test` installed (`pip install cocotb-test`)
- Either `RDS_RTL_PATH=/path/to/RTLDesignSherpa` or
  `tests/sim/_rds/` submodule initialized (for the AXI4 wrapper, gaxi,
  and converter RTL that the bridges depend on via `$REPO_ROOT` in
  their filelists)

Without these, `conftest.py` cleanly skips the whole `tests/sim/`
directory and only the Tier 1 unit tests run.

## Why these tests catch what they catch

The v0.1.1 BFM fixes (#3 per-ID R demux, #4 AW+W lock, #5 completion
locks) shipped without a regression test that explicitly stresses
those code paths under high concurrency. If those locks were removed
or downgraded, none of RDS's existing single-transaction-at-a-time
tests would catch the regression — but `bridge_c::same_id_completion_lock`
will, because it dispatches 24 same-ID writes via
`cocotb.start_soon` and verifies every B-response routed to the right
transaction. Same logic applies for `#15`'s APBSlave state machine
and APBMaster queued pipeline.

These tests are the **safety net** for those fixes.
