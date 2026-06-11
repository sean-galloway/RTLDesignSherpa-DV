# DFI BFM validation tests, per DRAM standard

Per-standard validation tests for the DFI BFM. Each subdirectory
targets one memory technology, with at least one DFI slave test and
one DFI master test using JEDEC timings + geometry for that standard.

## Status

| Standard | DFI version | Has tests? | JEDEC CSV |
|---|---|---|---|
| **ddr2** | v2.1+ | ✓ slave + master | `ddr2-650-mt47h64m16hr.csv` (Micron MT47H64M16HR-25:H, Digilent FPGA target) |
| lpddr2 | v2.1+ | — | — |
| ddr3 | v2.1+ | — | `ddr3-1600.csv` available |
| lpddr3 | v3.1+ | — | — |
| ddr4 | v3.1+ | — | — |
| lpddr4 | v4.0+ | — | — |
| ddr5 | v5.x | — | — |
| lpddr5 | v5.x | — | — |

## Test convention

For each standard:

- `test_dfi_slave_<std>.py` — verifies `DFISlavePHY` end-to-end: master
  writes through the shim, slave's DRAM state model + memory commit the
  writes, master reads them back, captured data matches.

- `test_dfi_master_<std>.py` — verifies `DFIMasterMC` end-to-end: master
  drives a representative command sequence for the standard, both
  monitors (MC- and PHY-side) capture identical packets, command
  decodes match the spec.

## Relationship to `tests/sim/dfi/`

`tests/sim/dfi/` contains the per-area proof-of-life tests (one per
semantic-shift area, exercising the behavior dispatch). This `val/`
tree is per-DRAM-standard end-to-end coverage. Both should pass before
any release.

## Adding a new standard

1. Vendor a JEDEC CSV under
   `src/CocoTBFramework/components/dfi/jedec/`. Cross-check timings
   against the LiteDRAM `modules.py` chip class or DRAMsim3 `.ini`
   config at `../../mem-ctrl-ref/`.
2. Add `tests/sim/val/<std>/test_dfi_slave_<std>.py` mirroring the
   DDR2 template.
3. Add `tests/sim/val/<std>/test_dfi_master_<std>.py` mirroring the
   DDR2 template.
4. Update this README's status table.
