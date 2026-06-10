# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""End-to-end proof-of-life: PHY-driven error → DFIv3_1Behavior → queue.

The slave drives ``phy_dfi_error`` + ``phy_dfi_error_info``; the shim
passes them through; the slave's ``_monitor_recv`` calls
``self.base.behavior.error_event(...)`` each cycle; the behavior
samples the wire and returns an ``ErrorEvent`` when ``error`` is
asserted; the event lands in ``slave.error_events``.

This is the first test that exercises the per-version-behavior
Strategy dispatch end-to-end against real RTL.
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
from CocoTBFramework.components.dfi.behaviors import ErrorKind
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
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut):
    """Build a v3.1 + DDR4 stack so DFIv3_1Behavior is the active class."""
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
    # Confirm registry plumbed the right behavior
    assert isinstance(base.behavior, DFIv3_1Behavior)
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_error_event_roundtrip_test(dut):
    """Slave pulses phy_dfi_error; behavior produces an ErrorEvent."""
    await _bring_up(dut)

    base, _, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    master.set_rddata_en(1)
    await Timer(1, units="ns")

    # Quiet baseline
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)
    assert len(slave.error_events) == 0, "got events with error=0"

    # Pulse one error event
    slave.set_error(active=1, info=0x42)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    slave.set_error(active=0)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    # Drain
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)

    dut._log.info(f"slave: {slave}")

    # ----- Assertions -----

    # At least one event captured during the assert window
    assert len(slave.error_events) >= 1, (
        f"expected at least 1 ErrorEvent, got {len(slave.error_events)}"
    )
    evt = slave.error_events[0]
    assert evt.kind == ErrorKind.OTHER
    assert evt.code == 0x42, f"expected code=0x42, got 0x{evt.code:x}"

    # Pulse a second error with a different code and verify the queue grows
    pre_count = len(slave.error_events)
    slave.set_error(active=1, info=0xab)
    await RisingEdge(dut.dfi_clk)
    slave.set_error(active=0)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    assert len(slave.error_events) > pre_count
    assert slave.error_events[-1].code == 0xab

    dut._log.info("Error-event end-to-end proof-of-life passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_error_event(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_error_event"
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
        module="test_dfi_error_event",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
