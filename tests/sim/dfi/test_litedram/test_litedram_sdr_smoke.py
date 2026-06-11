# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""SDR smoke test: 1:1 gear ratio + canonical SDR init.

SDR init sequence (from generated sdram_phy.h, MT48LC16M16, CL=2, BL=1):
    1. CKE up
    2. PRE_ALL
    3. MR (0x120) — DLL Reset, CL=2, BL=1
    4. PRE_ALL
    5. AUTO_REFRESH × 2
    6. MR (0x020) — CL=2, BL=1 (no DLL reset)

2 MRS + 2 PRE_ALL + 2 REF.

1:1 gear means phy_clk == clk; we drive both at 100 MHz so the
adapter drains 1 phase per clk = 1 phase per phy_clk.
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


async def litedram_sdr_init(dut):
    async def issue(cmd, addr, bank):
        await wb_ctrl_write(dut, pi0_adr(),  addr)
        await wb_ctrl_write(dut, pi0_bad(),  bank)
        await wb_ctrl_write(dut, pi0_cmd(),  cmd)
        await wb_ctrl_write(dut, pi0_iss(),  1)
        await _settle(dut, 6)

    await wb_ctrl_write(dut, pi0_adr(), 0x0)
    await wb_ctrl_write(dut, pi0_bad(), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                       CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)

    await issue(PRECHARGE, 0x400, 0)
    await issue(MRS,       0x120, 0)      # CL=2, BL=1 with DLL reset
    await _settle(dut, 30)
    await issue(PRECHARGE, 0x400, 0)
    await issue(REF,       0x000, 0)
    await issue(REF,       0x000, 0)
    await issue(MRS,       0x020, 0)      # CL=2, BL=1 no reset

    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 30)


async def _bring_up(dut, settle_cycles=20):
    # SDR: 1:1 gear → phy_clk == clk (same period)
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.phy_clk, 10, units="ns").start())
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


async def _sample_litedram_1phase(dut, adapter):
    """1-phase sampler — feed 1 dict per MC clock to the gear=1 adapter."""
    while True:
        await RisingEdge(dut.clk)
        phase = {}
        for sig in _PHASE_SIGNAL_NAMES:
            phase[sig] = int(getattr(dut, f"dfi_p0_{sig}").value)
        adapter.feed([phase])


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def litedram_sdr_smoke_test(dut):
    """SDR init: ≥2 MRS + ≥2 REF + ≥2 PRE."""
    await _bring_up(dut)

    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=4, num_rows=16, num_cols=16,   # SDR=4 banks
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR2,   # SDR not in our envelope; DDR2 closest
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=1024, bytes_per_line=16)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=1, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_1phase(dut, adapter))
    await Timer(1, units="ns")

    await litedram_sdr_init(dut)

    cmd_counts = dict(slave.cmd_counts)
    dut._log.info(f"After SDR init, cmd_counts: {cmd_counts}")
    dut._log.info(f"adapter: {adapter}")

    mrs  = cmd_counts.get(DRAMCommand.MRS, 0)
    ref  = cmd_counts.get(DRAMCommand.REF, 0)
    pre  = cmd_counts.get(DRAMCommand.PRE,  0)
    prea = cmd_counts.get(DRAMCommand.PREA, 0)

    dut._log.info(
        f"Summary: MRS={mrs}, REF={ref}, PRE={pre}, PREA={prea}"
    )

    assert mrs >= 2, f"SDR init should emit ≥2 MRS, got {mrs}"
    assert ref >= 2, f"SDR init should emit ≥2 REF, got {ref}"
    assert (pre + prea) >= 2, (
        f"SDR init should emit ≥2 PRE/PREA, got {pre}+{prea}"
    )

    dut._log.info("SDR init smoke PASSED — 1:1 gear ratio validated")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_sdr_smoke(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "sdr", "gateware", "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"SDR LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_sdr_smoke"
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
            os.path.join(litedram_dir, "litedram_cosim_top_sdr.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper_sdr.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top_sdr",
        module="test_litedram_sdr_smoke",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
