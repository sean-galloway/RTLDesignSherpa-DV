# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: Update interface request/grant handshake.

Two scenarios verifying both directions of the v3.0 bidirectional
handshake:
  1. PHY-initiated: slave drives phy_dfi_phyupd_req → behavior emits
     UpdateEvent(initiator="phy") → slave.update_events queue.
  2. MC-initiated: master drives mc_dfi_ctrlupd_req → behavior emits
     UpdateEvent(initiator="mc") → slave.update_events queue.
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
from CocoTBFramework.components.dfi.behaviors import UpdateState
from CocoTBFramework.components.dfi.behaviors.v3_1 import DFIv3_1Behavior
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
    dut.phy_dfi_crc_alert.value = 0
    dut.phy_dfi_ctrlupd_ack.value = 0
    dut.phy_dfi_phyupd_req.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    assert isinstance(base.behavior, DFIv3_1Behavior)
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_update_request_roundtrip_test(dut):
    """PHY-initiated and MC-initiated update requests both detected."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    # Quiet baseline
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)
    assert len(slave.update_events) == 0, "got events at idle"

    # ----- Scenario 1: PHY-initiated -----
    slave.set_phyupd_req(active=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    slave.set_phyupd_req(active=0)
    await RisingEdge(dut.dfi_clk)

    phy_initiated_events = [e for e in slave.update_events if e.initiator == "phy"]
    assert len(phy_initiated_events) >= 1, (
        f"expected at least 1 phy-initiated event, "
        f"got {len(phy_initiated_events)} (events: {list(slave.update_events)})"
    )
    assert phy_initiated_events[0].state == UpdateState.REQUESTED

    # ----- Scenario 2: MC-initiated -----
    pre_count = len(slave.update_events)
    master.set_ctrlupd_req(value=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    master.set_ctrlupd_req(value=0)
    await RisingEdge(dut.dfi_clk)

    new_events = list(slave.update_events)[pre_count:]
    mc_initiated_events = [e for e in new_events if e.initiator == "mc"]
    assert len(mc_initiated_events) >= 1, (
        f"expected at least 1 mc-initiated event after ctrlupd_req, "
        f"got {len(mc_initiated_events)} (new events: {new_events})"
    )

    dut._log.info(f"slave: {slave}")
    dut._log.info("Update request bidirectional handshake passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_update(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_update"
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
        module="test_dfi_update",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
