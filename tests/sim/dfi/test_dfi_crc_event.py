# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""End-to-end proof-of-life: PHY-driven CRC alert → DFIv3_1Behavior.crc()
→ slave.crc_events queue.

Mirrors the structure of ``test_dfi_error_event.py`` — same Strategy-
dispatch pattern proven for a second shift area. Confirms the
architecture is reusable: adding a new area is mostly catalog + shim +
behavior method + slave _dispatch_behavior_X helper.
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
from CocoTBFramework.components.dfi.behaviors import CRCKind
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
async def dfi_crc_alert_roundtrip_test(dut):
    """Slave pulses phy_dfi_crc_alert; behavior produces a CRCEvent."""
    await _bring_up(dut)

    base, _, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    master.set_rddata_en(1)
    await Timer(1, units="ns")

    # Quiet baseline
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)
    assert len(slave.crc_events) == 0, "got events with crc_alert=0"

    # Pulse a CRC alert
    slave.set_crc_alert(active=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    slave.set_crc_alert(active=0)
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)

    dut._log.info(f"slave: {slave}")

    # ----- Assertions -----

    assert len(slave.crc_events) >= 1, (
        f"expected at least 1 CRCEvent, got {len(slave.crc_events)}"
    )
    evt = slave.crc_events[0]
    assert evt.kind == CRCKind.DRAM_CRC
    assert evt.slice_idx == 0   # v3.0 MVP: single-slice

    # Second pulse to verify the queue grows
    pre_count = len(slave.crc_events)
    slave.set_crc_alert(active=1)
    await RisingEdge(dut.dfi_clk)
    slave.set_crc_alert(active=0)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    assert len(slave.crc_events) > pre_count

    # Bonus: error_events queue should be untouched — the two areas
    # have independent queues even though both flow through the same
    # _monitor_recv pass.
    assert len(slave.error_events) == 0

    dut._log.info("CRC alert end-to-end proof-of-life passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_crc_event(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_crc_event"
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
        module="test_dfi_crc_event",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
