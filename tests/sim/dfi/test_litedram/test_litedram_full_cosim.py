# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Full LiteDRAM ↔ DFI BFM slave co-sim.

End-to-end: real LiteDRAM MC emits DFI commands → cocotb sampler
captures 4 phases per cycle → DFIPhaseAdapter demuxes to 1-phase →
dfi_shim passes through → DFISlavePHY observes the command stream.

This is the test the whole co-sim infrastructure was built for. The
LiteDRAM MC is a non-our-BFM source of DFI traffic, so what the
slave sees here is an independent validation that our slave model
correctly interprets DFI emitted by a real controller.
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


# CSR addresses (from LiteDRAM's generated csr.h)
CSR_SDRAM_DFII_CONTROL           = 0x800
CSR_SDRAM_DFII_PI0_COMMAND       = 0x804
CSR_SDRAM_DFII_PI0_COMMAND_ISSUE = 0x808
CSR_SDRAM_DFII_PI0_ADDRESS       = 0x80c
CSR_SDRAM_DFII_PI0_BADDRESS      = 0x810

# DFII command bit positions
CMD_CS  = 1 << 0
CMD_WE  = 1 << 1
CMD_CAS = 1 << 2
CMD_RAS = 1 << 3
PRECHARGE_ALL = CMD_RAS | CMD_WE  | CMD_CS
MODE_REGISTER = CMD_RAS | CMD_CAS | CMD_WE | CMD_CS

# CONTROL bits
CKE_ODT_RESETN = (1 << 1) | (1 << 2) | (1 << 3)   # CKE=1, ODT=1, RESET_N=1


# DFI signal names (within each phase) we sample from the wrapper.
# These are the keys DFIPhaseAdapter expects in each phase dict.
_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    # rddata_en is the only MC→PHY signal in the read sub-interface;
    # rddata/rddata_valid are PHY→MC so we don't read them here.
    "rddata_en",
)


async def wb_ctrl_write(dut, addr: int, data: int, timeout: int = 100):
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


async def _bring_up(dut, settle_cycles: int = 10):
    # MC clock at 100 MHz (10 ns) — what LiteDRAM emits 4-phase DFI on.
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    # PHY clock at 400 MHz (2.5 ns) — what the adapter drains and the
    # slave samples on. 4× faster than clk per the 1:4 gear ratio, so
    # 4 phases arrive per clk and 4 phy_clks happen per clk → balanced.
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
    """Each MC clock, snapshot all 4 phases from LiteDRAM's DFI output
    and feed the batch to DFIPhaseAdapter. No throttling — phy_clk runs
    at 4× clk, so the adapter drains 4 phases per clk, exactly matching
    the feed rate."""
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(4):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                handle = getattr(dut, f"dfi_p{p}_{sig}")
                phase[sig] = int(handle.value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def litedram_full_cosim_test(dut):
    """LiteDRAM emits PRECHARGE_ALL + MRS; our slave sees them."""
    await _bring_up(dut)

    # ----- Build the DFI BFM slave stack (v3.1 + DDR4 envelope) -----
    timings = builtin_timings("ddr3-1600")    # close enough for capture
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16384, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    # Slave is attached to phy_dfi_* ports of the cosim_top and runs
    # on the fast PHY clock — same domain the adapter drives on.
    memory = MemoryModel(num_lines=128, bytes_per_line=8)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    # ----- Set up the DFIPhaseAdapter (4-phase → 1-phase) -----
    # Adapter drains one phase per dfi_clock edge. dfi_clock is the PHY
    # clock (fast), so for gear=4 with phy_clk=4× clk, the drain rate
    # exactly matches the 4-phases-per-clk feed rate.
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())

    # ----- Spawn the sampler that bridges LiteDRAM's 4-phase DFI -----
    cocotb.start_soon(_sample_litedram_4phase(dut, adapter))

    await Timer(1, units="ns")

    # Bring CKE up first (otherwise the DRAM model considers commands invalid)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CKE_ODT_RESETN)

    # Let the sampler settle, the slave see the idle bus
    for _ in range(20):
        await RisingEdge(dut.clk)

    # ----- Issue PRECHARGE_ALL -----
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  0x400)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  PRECHARGE_ALL)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
    # Give the sampler / adapter / slave time to settle
    for _ in range(50):
        await RisingEdge(dut.clk)

    # ----- Issue MRS for MR2 — but at bank 2 (no prior ACT needed) -----
    # NOTE: a v2.1 DDR3 MRS isn't quite a "bank ACT" — the DramStateModel's
    # MRS handler is a no-op. We just want to see the cmd count tick up.
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  0x0008)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, 2)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  MODE_REGISTER)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
    for _ in range(50):
        await RisingEdge(dut.clk)

    dut._log.info(f"slave: {slave}")
    dut._log.info(f"adapter: {adapter}")

    # ----- Assertions -----
    # The slave's cmd_counts should show PRE and MRS (the two we issued)
    pre_count = slave.cmd_counts.get(DRAMCommand.PRE, 0)
    mrs_count = slave.cmd_counts.get(DRAMCommand.MRS, 0)

    dut._log.info(f"cmd_counts: {dict(slave.cmd_counts)}")

    assert pre_count >= 1, (
        f"DFI slave never saw a PRE command — adapter or sampler "
        f"may be misaligned. cmd_counts={dict(slave.cmd_counts)}"
    )
    assert mrs_count >= 1, (
        f"DFI slave never saw an MRS command. cmd_counts={dict(slave.cmd_counts)}"
    )

    # Adapter should have driven at least a handful of phases — we feed
    # one 4-phase batch per active LiteDRAM cycle, so 2 commands = at
    # least 8 driven phases.
    assert adapter.phases_driven >= 8, (
        f"adapter under-fed: phases_driven={adapter.phases_driven}"
    )

    dut._log.info("FULL CO-SIM PASSED — LiteDRAM emits DFI, BFM slave consumes it")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_full_cosim(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_full_cosim"
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
            os.path.join(litedram_dir, "litedram_cosim_top.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top",
        module="test_litedram_full_cosim",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
