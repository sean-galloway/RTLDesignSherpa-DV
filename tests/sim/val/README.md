# DFI BFM validation tests, per DRAM standard

Per-standard validation tests for the DFI BFM. Each subdirectory
targets one memory technology.

## ⚠ Reality check — what these tests do and don't validate

The tests in this tree currently run our `DFIMasterMC` →
`dfi_shim.sv` (passthrough RTL) → our `DFISlavePHY`. **Both sides are
our BFM.** They are *internal-consistency tests configured for a
specific DRAM standard* — useful, but not independent validation.

| Test category | Catches | Doesn't catch |
|---|---|---|
| **Internal val** (this tree, today) | Per-standard JEDEC CSV math, command-set decode, addr[10] auto-pre / all-banks bits, internal state-model timing checks for that standard | Whether our master produces DFI patterns a real controller would emit; whether our slave models real DRAM behavior |
| **External co-sim with MC reference** (TBD) | Real-controller-vs-our-slave: a generated LiteDRAM controller's DFI output validates our slave's PHY/DRAM model | Doesn't validate our master |
| **External co-sim with PHY reference** (TBD) | Real-PHY-vs-our-master: LiteDRAM's behavioral PHY model receives our master's wire patterns and verifies they're spec-compliant | Doesn't validate our slave |

For "verifies the BFM is spec-compliant," **only the external-co-sim
columns count.** The internal val column proves the BFM is
internally consistent, not that it matches the spec.

## Status

| Standard | DFI ver. | Internal val | Co-sim (MC ref) | Co-sim (PHY ref) | JEDEC CSV |
|---|---|---|---|---|---|
| **ddr2** | v2.1+ | ✓ slave + master | — | — | `ddr2-650-mt47h64m16hr.csv` (Micron MT47H64M16HR-25:H, Digilent FPGA target) |
| lpddr2 | v2.1+ | — | — | — | — |
| ddr3 | v2.1+ | — | — | — | `ddr3-1600.csv` available |
| lpddr3 | v3.1+ | — | — | — | — |
| ddr4 | v3.1+ | — | — | — | — |
| lpddr4 | v4.0+ | — | — | — | — |
| ddr5 | v5.x | — | — | — | — |
| lpddr5 | v5.x | — | — | — | — |

## What's in each test

For each standard:

- `test_dfi_slave_<std>.py` — internal val: master writes through the
  shim, slave's DRAM state model + memory commit the writes, master
  reads them back, captured data matches, no JEDEC violations flagged.

- `test_dfi_master_<std>.py` — internal val: master drives a
  representative command sequence for the standard, both monitors
  (MC- and PHY-side) capture identical packet streams.

- `test_dfi_slave_<std>_litedram.py` — *(future)* external co-sim:
  generated LiteDRAM controller drives the MC side; our slave handles
  the traffic; verify writes/reads succeed against LiteDRAM's expected
  semantics.

- `test_dfi_master_<std>_litephy.py` — *(future)* external co-sim:
  our master drives LiteDRAM's behavioral PHY model; verify the PHY
  accepts the wire patterns.

## Relationship to `tests/sim/dfi/`

`tests/sim/dfi/` contains per-semantic-shift-area proof-of-life tests
(error / CRC / update / training / etc.) — those exercise the
per-version behavior dispatch end-to-end against the shim. They're
also internal-consistency tests, just sliced by behavior area rather
than by DRAM standard.

## Adding a new standard (internal val)

1. Vendor a JEDEC CSV under
   `src/CocoTBFramework/components/dfi/jedec/`. Cross-check timings
   against:
   - LiteDRAM `modules.py` chip class at
     `../../mem-ctrl-ref/litedram/litedram/modules.py`, or
   - DRAMsim3 `.ini` config at
     `../../mem-ctrl-ref/DRAMsim3/configs/`.
2. Add `tests/sim/val/<std>/test_dfi_slave_<std>.py` mirroring DDR2.
3. Add `tests/sim/val/<std>/test_dfi_master_<std>.py` mirroring DDR2.
4. Update the status table above.
5. **Remember:** the new test is still internal-consistency until
   somebody plumbs in an external reference.

## Adding external co-sim (future)

See task #47-48 in the project task list (LiteDRAM Verilog
generation, signal mapping, cocotb wire-up). When a co-sim lands for
a standard, add a `_litedram` or `_litephy` suffix to the test
filename and flip the status-table column.
