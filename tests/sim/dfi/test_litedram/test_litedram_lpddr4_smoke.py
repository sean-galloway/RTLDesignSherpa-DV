# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LPDDR4 smoke test: init sequence + command coverage via DFII.

First LPDDR4 LiteDRAM co-sim. The core comes from gen_lpddr4_sim.py
(MT53E256M16D1, real LPDDR4 controller timings and MRW init sequence,
1:4 DFI gearing — see that script for the litedram_gen workarounds).

Init is the generated sdram_phy.h sequence: reset staging, CKE up,
seven MRWs (MR1/2/3/11/12/13/14 — LPDDR4's MRW rides the DFII MRS
encoding with bank = MR index), then ZQ start + latch.

The DFI BFM slave runs a MemoryType.LPDDR4 + v4.0 envelope — the
first wire-level use of the LPDDR4 memory-type gating.
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
PI0_COMMAND       = 0x804
PI0_COMMAND_ISSUE = 0x808
PI0_ADDRESS       = 0x80c
PI0_BADDRESS      = 0x810

CTRL_CKE, CTRL_ODT, CTRL_RESET_N = 0x02, 0x04, 0x08

CMD_CS, CMD_WE, CMD_CAS, CMD_RAS = 0x01, 0x02, 0x04, 0x08
MRW       = CMD_RAS | CMD_CAS | CMD_WE | CMD_CS   # LPDDR4 MRW via MRS encoding
ZQC       = CMD_WE | CMD_CS
ACTIVATE  = CMD_RAS | CMD_CS
WRITE     = CMD_CAS | CMD_WE | CMD_CS
READ      = CMD_CAS | CMD_CS
PRECHARGE = CMD_RAS | CMD_WE | CMD_CS

# Generated init MRW list (sdram_phy.h): (MR value, MR index)
LPDDR4_MRWS = (
    (0x24, 1), (0x12, 2), (0x11, 3),
    (0x22, 11), (0x55, 12), (0x00, 13), (0x55, 14),
)

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)


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


async def _issue(dut, command, address=0, bank=0, settle=8):
    await wb_ctrl_write(dut, PI0_ADDRESS,  address)
    await wb_ctrl_write(dut, PI0_BADDRESS, bank)
    await wb_ctrl_write(dut, PI0_COMMAND,  command)
    await wb_ctrl_write(dut, PI0_COMMAND_ISSUE, 1)
    await _settle(dut, settle)


async def litedram_lpddr4_init(dut):
    """Generated LPDDR4 init: reset staging, CKE, 7 MRWs, ZQ."""
    await wb_ctrl_write(dut, PI0_ADDRESS, 0x0)
    await wb_ctrl_write(dut, PI0_BADDRESS, 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CTRL_ODT)
    await _settle(dut, 100)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 100)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 100)
    for value, mr in LPDDR4_MRWS:
        await _issue(dut, MRW, address=value, bank=mr, settle=12)
    await _issue(dut, ZQC, address=0x4F, bank=0, settle=20)   # ZQ start
    await _issue(dut, ZQC, address=0x51, bank=0, settle=20)   # ZQ latch
    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 30)


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
        "mc_dfi_ctrlupd_req", "mc_dfi_phyupd_ack",
        "mc_dfi_rdlvl_en", "mc_dfi_rdlvl_gate_en", "mc_dfi_wrlvl_en",
        "mc_dfi_parity_in", "mc_dfi_init_start", "mc_dfi_freq_ratio",
        "mc_dfi_frequency", "mc_dfi_lp_ctrl_req", "mc_dfi_lp_data_req",
        "mc_dfi_lp_wakeup", "mc_dfi_disconnect_error",
        "mc_dfi_phymstr_ack",
    ):
        getattr(dut, sig).value = 0
    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


async def _sample_4phase(dut, adapter):
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(4):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                phase[sig] = int(getattr(dut, f"dfi_p{p}_{sig}").value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=60, timeout_unit="ms")
async def litedram_lpddr4_smoke_test(dut):
    """LPDDR4 init + ACT/WR/RD/PRE all decoded by the LPDDR4 slave."""
    await _bring_up(dut)

    timings = builtin_timings("ddr3-1600")   # capture-grade (no LPDDR4 CSV yet)
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=32768, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V4_0,
        memory_type=MemoryType.LPDDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=128, bytes_per_line=8)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_4phase(dut, adapter))
    await Timer(1, units="ns")

    await litedram_lpddr4_init(dut)

    # Command coverage: ACT / WR / RD / PRE rounds
    for i in range(3):
        bank = i % 4
        await _issue(dut, ACTIVATE, address=0x20 + i, bank=bank)
        await _issue(dut, WRITE,    address=0x8,      bank=bank)
        await _issue(dut, READ,     address=0x8,      bank=bank)
        await _issue(dut, PRECHARGE, address=0x400,   bank=bank)
    await _settle(dut, 30)

    counts = dict(slave.cmd_counts)
    dut._log.info(f"cmd_counts: {counts}")

    # Init observed: 7 MRWs (+ any repeats) ride the MRS decode
    assert counts.get(DRAMCommand.MRS, 0) >= len(LPDDR4_MRWS), (
        f"expected >= {len(LPDDR4_MRWS)} MRW/MRS, got "
        f"{counts.get(DRAMCommand.MRS, 0)}"
    )
    for cmd in (DRAMCommand.ACT, DRAMCommand.WR, DRAMCommand.RD,
                DRAMCommand.PRE):
        assert counts.get(cmd, 0) >= 3, (
            f"missing {cmd}: {counts}"
        )
    assert adapter.phases_driven > 0

    dut._log.info("LPDDR4 co-sim smoke passed — first LPDDR4 wire coverage")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_lpddr4_smoke(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "lpddr4", "gateware",
                          "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LPDDR4 core missing (run "
                    f"gen_lpddr4_sim.py): {core_v}")

    test_name = "test_litedram_lpddr4_smoke"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build",
                             test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

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
            os.path.join(litedram_dir, "litedram_cosim_top_lpddr4.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper_lpddr4.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi",
                         "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top_lpddr4",
        module="test_litedram_lpddr4_smoke",
        sim_build=sim_build,
        extra_env={
            "COCOTB_LOG_LEVEL": "INFO",
            "COCOTB_RESULTS_FILE": os.path.join(
                log_dir, f"results_{test_name}.xml"),
        },
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
