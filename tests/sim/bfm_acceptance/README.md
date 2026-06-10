# BFM Acceptance Tests

cocotb-test driven tests pulled from RDS `val/amba/` and `val/integ_amba/`.
These exercise the framework BFMs against real RTL DUTs from RDS — the
**framework's own regression**, independent of (and additional to) what
RDS's `val/` suite does.

## Test files (initial set)

| Test | RDS source | Exercises | Migration needed for v0.2.0 |
|---|---|---|---|
| `test_gaxi_fifo_sync.py` | `val/amba/` | GAXI BFMs wrapping a sync FIFO — exercises FIFOMaster/FIFOSlave/FIFOMonitor (FIFO base merge from #6 — should be transparent) | None expected (FIFOComponentBase is a transparent alias) |
| `test_gaxi_buffer_field.py` | `val/integ_amba/` | GAXI multi-field packets (FieldConfig + Packet) | None expected |
| `test_gaxi_buffer_multi.py` | `val/integ_amba/` | GAXI `multi_sig=True` mode | None expected |
| `test_gaxi_buffer_multi_sigmap.py` | `val/integ_amba/` | GAXI manual `signal_map` override | None expected |
| `test_apb_master.py` | `val/amba/` | APBMaster queued pipeline + APBSlave + APB↔GAXI scoreboard | **Possibly affected by #15** — APBSlave's `_monitor_recv` now dispatches via `self._recv()` and seeded memory overflow auto-expands. Watch the scoreboard for new packet sources. |
| `test_apb5_master.py` | `val/amba/` | APB5Master queued pipeline | **Affected by #15 Phase A** — `await master.send(...)` now returns after queuing, not after the transaction completes on the bus. Use `await master.busy_send(...)` where the test needs completion. |

More tests can be brought in incrementally (the goal is BFM coverage, not
re-running the entire RDS val suite — RDS still owns that).

## How to run

```bash
# From the DV repo root
python -m venv .venv-tier2
.venv-tier2/bin/pip install -e .
.venv-tier2/bin/pip install pytest cocotb cocotb-bus cocotb-test

# Tell conftest where RDS lives (for $REPO_ROOT substitution in filelists)
export RDS_RTL_PATH=/path/to/RTLDesignSherpa

# Run a single BFM acceptance test
.venv-tier2/bin/python -m pytest tests/sim/bfm_acceptance/test_gaxi_fifo_sync.py -v

# Or the whole suite
.venv-tier2/bin/python -m pytest tests/sim/bfm_acceptance/ -v
```

## Dependencies

- **Verilog simulator on PATH**: Verilator (recommended for speed),
  Icarus, ModelSim, or Xcelium. `conftest.py` auto-skips tests if none
  is found.
- **`RDS_RTL_PATH` or the `_rds/` submodule**: provides the RTL files
  and the `+incdir+` paths the BFMs need to compile against.
- **`TBClasses/` snapshot**: `tbbase.py`, `utilities.py`, etc. —
  imported as `TBClasses.*` by all tests (`conftest.py` wires this up).
  Synced from RDS `bin/TBClasses/` — see `TBClasses/PROVENANCE.md`.

## Workflow when RDS or DV changes

| Scenario | Action |
|---|---|
| BFM API changes here (e.g. new framework kwarg) | Update relevant acceptance test, document migration in CHANGELOG |
| New RDS commit you want to track | Update `RDS_VERSION` in `tests/sim/rtl/README.md`; re-sync `TBClasses/` from RDS `bin/TBClasses/` |
| New BFM coverage gap | Copy another test from RDS `val/amba/` and migrate as needed |
| New bridge config you want to test | Add TOML to `tests/sim/bridge_specs/`, generate RTL in RDS, copy generated to `tests/sim/rtl/bridges/` |
