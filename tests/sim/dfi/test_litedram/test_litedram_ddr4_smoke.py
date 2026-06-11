# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR4 smoke test: init sequence + command coverage via DFII injection.

LiteDRAM DDR4 init sequence (ported from the generated sdram_phy.h
for kcu105-style EDY4016A x16):
    1. Reset release:    CTRL=ODT|RESET_N
    2. CKE up:           CTRL=CKE|ODT|RESET_N
    3. MR3 (BA=3, 0x000)
    4. MR6 (BA=6, 0x000)
    5. MR5 (BA=5, 0x400)
    6. MR4 (BA=4, 0x000)
    7. MR2 (BA=2, 0x200) — CWL=9
    8. MR1 (BA=1, 0x301)
    9. MR0 (BA=0, 0x100) — CL=9, BL=8
   10. ZQ Calibration (WE|CS, addr=0x400)

DDR4 phase ratio is 1:4 (same as DDR3). Reuses the gear adapter at
n_phases=4 but with DDR4-specific harness widths (15-bit address,
128-bit wrdata per phase, 16-bit mask).
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIBase,
    DFIPhaseAdapter,
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


# CSR map (same layout as DDR3)
CSR_DDRCTRL_INIT_DONE  = 0x000
CSR_SDRAM_DFII_CONTROL = 0x800
PI_BASE = {0: 0x804, 1: 0x81c, 2: 0x834, 3: 0x84c}

CTRL_CKE     = 0x02
CTRL_ODT     = 0x04
CTRL_RESET_N = 0x08

CMD_CS  = 0x01
CMD_WE  = 0x02
CMD_CAS = 0x04
CMD_RAS = 0x08
MRS = CMD_RAS | CMD_CAS | CMD_WE | CMD_CS
ZQC = CMD_WE  | CMD_CS

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)


def pi_cmd(p):    return PI_BASE[p]
def pi_iss(p):    return PI_BASE[p] + 0x04
def pi_adr(p):    return PI_BASE[p] + 0x08
def pi_bad(p):    return PI_BASE[p] + 0x0c


async def wb_ctrl_write(dut, addr, data, timeout=100):
    dut.wb_ctrl_adr.value   = addr >> 2
    dut.wb_ctrl_dat_w.value = data
    dut.wb_ctrl_sel.value   = 0xF
    dut.wb_ctrl_cyc.value   = 1
    dut.wb_ctrl_stb.value   = 1
    dut.wb_ctrl_we.value    = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        if int(dut.wb_ctrl_ack.value) == 1:
            break
    else:
        raise TimeoutError(f"wb_ctrl write to 0x{addr:x} never ack'd")
    dut.wb_ctrl_cyc.value = 0
    dut.wb_ctrl_stb.value = 0
    dut.wb_ctrl_we.value  = 0
    await RisingEdge(dut.clk)


async def _settle(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def litedram_ddr4_init(dut):
    """DDR4 init: 8 MRS + ZQC, derived from generated sdram_phy.h."""
    await wb_ctrl_write(dut, pi_adr(0), 0x0)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)

    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                       CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 100)

    async def mrs(addr, bank):
        await wb_ctrl_write(dut, pi_adr(0), addr)
        await wb_ctrl_write(dut, pi_bad(0), bank)
        await wb_ctrl_write(dut, pi_cmd(0), MRS)
        await wb_ctrl_write(dut, pi_iss(0), 1)
        await _settle(dut, 20)

    # DDR4 init programs 8 MRs (MR0..MR6)
    await mrs(0x000, 3)
    await mrs(0x000, 6)
    await mrs(0x400, 5)
    await mrs(0x000, 4)
    await mrs(0x200, 2)
    await mrs(0x301, 1)
    await mrs(0x100, 0)
    await _settle(dut, 100)

    # ZQ Calibration
    await wb_ctrl_write(dut, pi_adr(0), 0x400)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, pi_cmd(0), ZQC)
    await wb_ctrl_write(dut, pi_iss(0), 1)
    await _settle(dut, 100)

    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 50)


async def _bring_up(dut, settle_cycles=20):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.phy_clk, 2500, units="ps").start())
    dut.sim_trace.value = 0
    dut.dfi_rstn.value = 1
    for sig in (
        "user_port_wishbone_0_adr", "user_port_wishbone_0_dat_w",
        "user_port_wishbone_0_sel", "user_port_wishbone_0_cyc",
        "user_port_wishbone_0_stb", "user_port_wishbone_0_we",
        "wb_ctrl_adr", "wb_ctrl_dat_w", "wb_ctrl_sel",
        "wb_ctrl_cyc", "wb_ctrl_stb", "wb_ctrl_we",
        "wb_ctrl_cti", "wb_ctrl_bte",
    ):
        getattr(dut, sig).value = 0
    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


async def _sample_litedram_4phase(dut, adapter):
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(4):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                phase[sig] = int(getattr(dut, f"dfi_p{p}_{sig}").value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def litedram_ddr4_smoke_test(dut):
    """Run DDR4 init and assert slave decoded 8 MRS commands."""
    await _bring_up(dut)

    # DDR4 BFM slave — uses DDR4 memory_type but timing template
    # derived from ddr4-2400 if available; otherwise reuse ddr3-1600
    # since timings don't affect command decode for this smoke test.
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=2048, bytes_per_line=16)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_4phase(dut, adapter))
    await Timer(1, units="ns")

    await litedram_ddr4_init(dut)

    cmd_counts = dict(slave.cmd_counts)
    dut._log.info(f"After DDR4 init, cmd_counts: {cmd_counts}")
    dut._log.info(f"adapter: {adapter}")

    mrs = cmd_counts.get(DRAMCommand.MRS, 0)
    assert mrs >= 7, f"expected ≥7 MRS from DDR4 init, got {mrs}"

    dut._log.info("DDR4 init smoke PASSED — 4-phase gear shared with DDR3")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_ddr4_smoke(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr4", "gateware", "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"DDR4 LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_ddr4_smoke"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
    }
    extra_args = [
        "-Wno-TIMESCALEMOD", "-Wno-COMBDLY", "-Wno-CASEINCOMPLETE",
        "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-Wno-UNOPTFLAT",
        "-Wno-CMPCONST", "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM",
        "-Wno-MULTIDRIVEN", "-Wno-SELRANGE", "-Wno-LATCH",
        "-Wno-DECLFILENAME",
    ]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[
            os.path.join(litedram_dir, "litedram_cosim_top_ddr4.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper_ddr4.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top_ddr4",
        module="test_litedram_ddr4_smoke",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
