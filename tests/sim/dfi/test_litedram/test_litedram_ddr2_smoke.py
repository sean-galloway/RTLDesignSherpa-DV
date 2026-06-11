# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR2 smoke test: 1:2 gear ratio + init sequence verification.

DDR2 init sequence (from generated sdram_phy.h, MT47H64M16, CL=3, BL=4):
    1. CKE up
    2. PRE_ALL
    3. EMR3 (BA=3)
    4. EMR2 (BA=2)
    5. EMR1 (BA=1)
    6. MR0 (BA=0, 0x532) — DLL Reset, CL=3, BL=4
    7. PRE_ALL
    8. AUTO_REFRESH × 2
    9. MR0 (BA=0, 0x432) — CL=3, BL=4 (no DLL reset)
   10. EMR1 (BA=1, 0x380) — OCD Default
   11. EMR1 (BA=1, 0x000) — OCD Exit

7 MRS commands + 2 PRE_ALL + 2 REF total.

DDR2 phase ratio is 1:2 — adapter set to n_phases=2. phy_clk runs at
2× mc_clk so the gear math balances (2 phases in per mc_clk, 2 phases
drained per mc_clk).
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


CSR_DDRCTRL_INIT_DONE  = 0x000
CSR_SDRAM_DFII_CONTROL = 0x800
# DDR2 only has 2 PI registers (PI0, PI1). Their stride may differ;
# we re-derive PI1_BASE from the generated csr.h at runtime later if
# needed — for init we only use PI0.
PI0_BASE = 0x804

CTRL_CKE     = 0x02
CTRL_ODT     = 0x04
CTRL_RESET_N = 0x08

CMD_CS  = 0x01
CMD_WE  = 0x02
CMD_CAS = 0x04
CMD_RAS = 0x08

PRECHARGE = CMD_RAS                | CMD_WE | CMD_CS
MRS       = CMD_RAS | CMD_CAS      | CMD_WE | CMD_CS
REF       = CMD_RAS | CMD_CAS               | CMD_CS

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)


def pi0_cmd():  return PI0_BASE
def pi0_iss():  return PI0_BASE + 0x04
def pi0_adr():  return PI0_BASE + 0x08
def pi0_bad():  return PI0_BASE + 0x0c


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


async def litedram_ddr2_init(dut):
    """Canonical DDR2 init: 7 MRS + 2 PRE + 2 REF."""

    async def issue(cmd, addr, bank):
        await wb_ctrl_write(dut, pi0_adr(),  addr)
        await wb_ctrl_write(dut, pi0_bad(),  bank)
        await wb_ctrl_write(dut, pi0_cmd(),  cmd)
        await wb_ctrl_write(dut, pi0_iss(),  1)
        await _settle(dut, 8)

    # CKE up
    await wb_ctrl_write(dut, pi0_adr(), 0x0)
    await wb_ctrl_write(dut, pi0_bad(), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                       CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)

    await issue(PRECHARGE, 0x400, 0)
    await issue(MRS,       0x000, 3)
    await issue(MRS,       0x000, 2)
    await issue(MRS,       0x000, 1)
    await issue(MRS,       0x532, 0)      # MR0 with DLL Reset
    await _settle(dut, 50)
    await issue(PRECHARGE, 0x400, 0)
    await issue(REF,       0x000, 0)
    await issue(REF,       0x000, 0)
    await issue(MRS,       0x432, 0)      # MR0 normal
    await _settle(dut, 30)
    await issue(MRS,       0x380, 1)      # EMR1 OCD Default
    await issue(MRS,       0x000, 1)      # EMR1 OCD Exit

    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 50)


async def _bring_up(dut, settle_cycles=20):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    # phy_clk at 2× clk for the 1:2 gear ratio (200 MHz vs 100 MHz)
    cocotb.start_soon(Clock(dut.phy_clk, 5000, units="ps").start())
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


async def _sample_litedram_2phase(dut, adapter):
    """Each MC clock, snapshot all 2 phases and feed to the gear=2
    adapter."""
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(2):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                phase[sig] = int(getattr(dut, f"dfi_p{p}_{sig}").value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def litedram_ddr2_smoke_test(dut):
    """DDR2 init + slave decodes ≥7 MRS + ≥2 REF + ≥2 PRE/PREA."""
    await _bring_up(dut)

    timings = builtin_timings("ddr3-1600")  # generic; not critical for smoke
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR2,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=2048, bytes_per_line=16)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=2, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_2phase(dut, adapter))
    await Timer(1, units="ns")

    await litedram_ddr2_init(dut)

    cmd_counts = dict(slave.cmd_counts)
    dut._log.info(f"After DDR2 init, cmd_counts: {cmd_counts}")
    dut._log.info(f"adapter: {adapter}")

    mrs  = cmd_counts.get(DRAMCommand.MRS, 0)
    ref  = cmd_counts.get(DRAMCommand.REF, 0)
    pre  = cmd_counts.get(DRAMCommand.PRE,  0)
    prea = cmd_counts.get(DRAMCommand.PREA, 0)

    dut._log.info(
        f"Summary: MRS={mrs}, REF={ref}, PRE={pre}, PREA={prea}"
    )

    assert mrs >= 7, f"DDR2 init should emit ≥7 MRS, got {mrs}"
    assert ref >= 2, f"DDR2 init should emit ≥2 REF, got {ref}"
    assert (pre + prea) >= 2, (
        f"DDR2 init should emit ≥2 PRE/PREA, got {pre}+{prea}"
    )

    dut._log.info("DDR2 init smoke PASSED — 1:2 gear adapter works")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_ddr2_smoke(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr2", "gateware", "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"DDR2 LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_ddr2_smoke"
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
            os.path.join(litedram_dir, "litedram_cosim_top_ddr2.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper_ddr2.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top_ddr2",
        module="test_litedram_ddr2_smoke",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
