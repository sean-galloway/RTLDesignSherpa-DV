# LiteDRAM generation for DFI BFM co-sim

This directory holds the input YAML config + regen script for
generating a standalone LiteDRAM controller as Verilog, suitable
for end-to-end DFI BFM co-sim under verilator.

## What's here

- `arty_ddr3_nocpu.yml` — YAML config (based on
  `mem-ctrl-ref/litedram/examples/arty.yml`) with `cpu: None` and
  `user_ports: wishbone_0` only. Targets DDR3 (MT41K128M16,
  the part on the Digilent Arty A7 board) at sys_clk=100 MHz with
  the canonical 4-phase DFI (1:4 MC:DRAM frequency ratio).
- `regen.sh` — runs `litedram_gen --sim --no-compile` against the YAML
- `migen_py312_tracer.patch` — Python 3.12 compatibility patch for
  Migen's bytecode tracer. Required because Migen 0.9.2 doesn't
  understand the new `CALL` opcode or inline CACHE entries.

## Generated artifacts (not committed)

`ddr3/gateware/litedram_core.v` — ~15 K lines of Verilog containing:
  - LiteDRAM MC core
  - Behavioral PHY model (`SDRAMPHYModel` — substituted by the `--sim` flag)
  - Behavioral DRAM model (so the core runs closed-loop)
  - Wishbone host port for cocotb to drive

The DFI signals (4 phases × ~16 signals each) are **internal wires**
at the top level of `litedram_core`, accessible from cocotb via
hierarchy: `dut.soc_litedramcore_master_p0_address` etc.

## One-time setup

Required Python packages (all available on PyPI / GitHub):

```bash
source env_python
pip install litedram litex migen pyyaml \
            liteeth liteiclink litescope litesata litesdcard
pip install 'pythondata-misc-tapcfg @ git+https://github.com/litex-hub/pythondata-misc-tapcfg.git'
```

Apply the Migen patch (required for Python 3.12):

```bash
cd $(python3 -c "import migen, os; print(os.path.dirname(migen.__file__))")
patch -p1 < /mnt/data/github/RTLDesignSherpa-DV/tests/sim/rtl/litedram/migen_py312_tracer.patch
```

If you re-create the venv, reapply the patch.

## Regenerate

```bash
source env_python
./tests/sim/rtl/litedram/regen.sh
```

Output: `tests/sim/rtl/litedram/ddr3/gateware/litedram_core.v`.

## DFI exposure: the wrapper

LiteDRAM emits 4-phase DFI as **internal** wires (between MC and the
behavioral PHY model). Rather than probing internals via cocotb
hierarchy + `--public-flat-rw`, `litedram_dfi_wrapper.sv` makes them
proper top-level ports via SystemVerilog out-of-module references.

The cocotb test instantiates `litedram_dfi_wrapper`, drives Wishbone
on the host port, and observes 4-phase DFI as flat ports:

```python
# Phase 0 (and identical for p1, p2, p3)
dut.dfi_p0_address       # 14-bit
dut.dfi_p0_bank          # 3-bit
dut.dfi_p0_act_n         # DDR4 ACT_n (unused for DDR3)
dut.dfi_p0_cas_n / ras_n / we_n / cs_n / cke / odt / reset_n
dut.dfi_p0_wrdata        # 32-bit
dut.dfi_p0_wrdata_en
dut.dfi_p0_wrdata_mask   # 4-bit
dut.dfi_p0_rddata        # 32-bit
dut.dfi_p0_rddata_en
dut.dfi_p0_rddata_valid
```

16 signals × 4 phases = 64 ports. The wrapper is **observation-only**
on the DFI side (no signals driven inward), so the MC's behavioral
PHY+DRAM model still runs closed-loop. Our `DFIPhaseAdapter(n_phases=4)`
samples these ports and demuxes them into the 1-phase `DFISlavePHY`.

## Why a wrapper, not internal hierarchy access

- Verilator wouldn't need `--public-flat-rw`
- xsim / questa / vcs all see normal ports
- The hierarchy paths inside the generated Verilog can change between
  LiteDRAM versions (regen could rename `soc_litedramcore_master_p0_*`
  to something else); the wrapper isolates the dependency
- An eventual swap of the host interface (Wishbone → AXI4 via a
  converter) is just a different set of wrapper ports — no test-side
  changes required
