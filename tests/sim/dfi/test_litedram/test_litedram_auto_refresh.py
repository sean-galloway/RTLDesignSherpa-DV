# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LiteDRAM auto-refresh co-sim: REF cadence observed at the DFI slave.

Every other LiteDRAM co-sim test drives commands through the DFII
software-injection port (dfii_control sel=0). This test flips the DFII
mux to HARDWARE control (sel=1) so the real LiteDRAM MC owns the DFI
bus — its refresh timer then issues REF commands autonomously at its
generated tREFI cadence, through the shim, into the DFISlavePHY.

What it proves:

  1. The slave decodes MC-issued (not testbench-issued) REF commands.
  2. The observed cadence matches the controller's refresh timer
     (tREFI ≈ 7.8 us => ~781 MC cycles at the 100 MHz sim clock).
  3. The DramStateModel's refresh checks stay clean against a real
     refresher: no ref_with_open_row / cmd_during_refresh (hard —
     they'd throw), and no tREFI-overdue soft violations now that
     tREFI windowing is implemented.
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


CSR_SDRAM_DFII_CONTROL = 0x800

DFII_CONTROL_SEL = 0x01     # 1 = hardware (MC) control of the DFI
CTRL_CKE, CTRL_ODT, CTRL_RESET_N = 0x02, 0x04, 0x08

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)

_MC_HANDSHAKE_WIRES = (
    "mc_dfi_ctrlupd_req", "mc_dfi_phyupd_ack",
    "mc_dfi_rdlvl_en", "mc_dfi_rdlvl_gate_en", "mc_dfi_wrlvl_en",
    "mc_dfi_parity_in",
    "mc_dfi_init_start", "mc_dfi_freq_ratio", "mc_dfi_frequency",
    "mc_dfi_lp_ctrl_req", "mc_dfi_lp_data_req", "mc_dfi_lp_wakeup",
    "mc_dfi_disconnect_error", "mc_dfi_phymstr_ack",
)

# LiteDRAM arty-class sim config: 100 MHz sys clock, 64 ms / 8192 rows
# refresh => tREFI ~ 7.8125 us ~ 781 MC cycles.
EXPECTED_REFI_MC_CYCLES = 781
OBSERVE_MC_CYCLES = 2600     # ~3.3 refresh intervals


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


async def _hold(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


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
    for sig in _MC_HANDSHAKE_WIRES:
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


@cocotb.test(timeout_time=120, timeout_unit="ms")
async def litedram_auto_refresh_test(dut):
    await _bring_up(dut)

    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16384, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR3,
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

    # Stage CKE up in software mode (mirrors the hardware init tail),
    # then hand the DFI to the MC. From here the controller's refresh
    # timer owns the bus.
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _hold(dut, 10)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, DFII_CONTROL_SEL)

    # Let one partial interval elapse before measuring, then observe.
    await _hold(dut, 100)
    ref_at_start = slave.cmd_counts.get(DRAMCommand.REF, 0)
    await _hold(dut, OBSERVE_MC_CYCLES)
    ref_observed = slave.cmd_counts.get(DRAMCommand.REF, 0) - ref_at_start

    dut._log.info(f"cmd_counts: {dict(slave.cmd_counts)}")
    dut._log.info(f"REF in {OBSERVE_MC_CYCLES} MC cycles: {ref_observed}")

    # ----- Cadence: expect OBSERVE/tREFI refreshes (+/- 1 for phase) --
    expected = OBSERVE_MC_CYCLES // EXPECTED_REFI_MC_CYCLES
    assert ref_observed >= max(1, expected - 1), (
        f"MC refresher too slow or REF not decoded: {ref_observed} REF "
        f"in {OBSERVE_MC_CYCLES} cycles (expected ~{expected})"
    )
    assert ref_observed <= expected + 2, (
        f"implausibly many REFs: {ref_observed} (expected ~{expected}) "
        f"— decoder may be double-counting"
    )

    # ----- Refresh-model checks stayed clean -----
    # Hard ones (ref_with_open_row / cmd_during_refresh) would have
    # thrown mid-sim. Soft: no tREFI-overdue, no tRFC complaints.
    soft = slave.dram.policy.soft_violation_counts
    assert soft.get("tREFI", 0) == 0, f"refresh went overdue: {soft}"
    assert soft.get("tRFC", 0) == 0, f"tRFC violations: {soft}"

    dut._log.info("MC auto-refresh cadence verified at the DFI slave")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_auto_refresh(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_auto_refresh"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build",
                             test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(
            log_dir, f"results_{test_name}.xml"),
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
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi",
                         "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top",
        module="test_litedram_auto_refresh",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
