# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: Frequency change via dfi_init_start.

Spec-verified protocol (every DFI version): the MC requests a
frequency change by asserting dfi_init_start during normal operation
(dfi_init_complete high); the PHY accepts by de-asserting
dfi_init_complete within tinit_start cycles. There is no dedicated
freq-change request wire. v4.0+ adds the dfi_frequency indicator,
which the v4.0 behavior captures into the event.
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
    DFIMasterMC,
    DFIVersion,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.behaviors import (
    DFIv3_1Behavior,
    DFIv4_0Behavior,
    FreqChangeProtocol,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


BANKS, ROWS, COLS, BYTES_PER_BEAT = 4, 16, 32, 8


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    dut.phy_dfi_rddata.value = 0
    dut.phy_dfi_rddata_valid.value = 0
    dut.phy_dfi_error.value = 0
    dut.phy_dfi_error_info.value = 0
    dut.phy_dfi_alert_n.value = 1
    dut.phy_dfi_ctrlupd_ack.value = 0
    dut.phy_dfi_phyupd_req.value = 0
    dut.phy_dfi_rdlvl_req.value = 0
    dut.phy_dfi_rdlvl_gate_req.value = 0
    dut.phy_dfi_wrlvl_req.value = 0
    dut.phy_dfi_rdlvl_resp.value = 0
    dut.phy_dfi_wrlvl_resp.value = 0
    dut.phy_dfi_phyupd_type.value = 0
    dut.phy_dfi_lp_ack.value = 0
    dut.phy_dfi_parity_error.value = 0
    dut.phy_dfi_init_complete.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut, version):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=version,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_freq_change_v3_1_basic_test(dut):
    """v3.1: init_start assertion during normal operation emits a
    BASIC-protocol event carrying the freq_ratio."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut, DFIVersion.V3_1)
    assert isinstance(base.behavior, DFIv3_1Behavior)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    # Slave asserts init_complete at construction; request = init_start
    master.request_freq_change(freq_ratio=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    master.set_init_start(0)
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)

    assert len(slave.freq_change_events) >= 1
    evt = slave.freq_change_events[0]
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.freq_ratio == 1


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_freq_change_v4_0_indicator_and_accept_test(dut):
    """v4.0: the event captures the dfi_frequency indicator, and the
    PHY accepts by de-asserting dfi_init_complete (visible MC-side)."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut, DFIVersion.V4_0)
    assert isinstance(base.behavior, DFIv4_0Behavior)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    master.request_freq_change(frequency_code=7, freq_ratio=2)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    assert len(slave.freq_change_events) >= 1, "no freq-change event"
    evt = slave.freq_change_events[0]
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.frequency_code == 7
    assert evt.freq_ratio == 2

    # PHY accepts: de-assert init_complete; MC sees it fall
    slave.accept_freq_change()
    await RisingEdge(dut.dfi_clk)
    await Timer(1, units="ns")
    assert dut.mc_dfi_init_complete.value == 0

    # Frequency change done: MC drops the request, PHY re-inits
    master.set_init_start(0)
    slave.set_init_complete(1)
    await RisingEdge(dut.dfi_clk)
    await Timer(1, units="ns")
    assert dut.mc_dfi_init_complete.value == 1

    dut._log.info(f"slave: {slave}")
    dut._log.info("v4.0 init_start/init_complete freq_change passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_freq_change(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_freq_change"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    verilog_sources = [
        os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
    ]
    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
    }
    extra_args = [
        "-Wno-TIMESCALEMOD",
        "-Wno-UNUSED",
        "-Wno-DECLFILENAME",
    ]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=verilog_sources,
        toplevel="dfi_shim",
        module="test_dfi_freq_change",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
