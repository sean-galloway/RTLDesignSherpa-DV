# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""End-to-end scoreboard test: real BFM + behavior + DFIScoreboard.

Demonstrates the scoreboard catching events from multiple areas in one
sim. The slave drives error / CRC / training / disconnect / takeover
signals; the behavior emits events; the scoreboard drains them via
callbacks and counts. Uses on_any to verify generic routing also works.
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
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel
from CocoTBFramework.scoreboards.dfi_scoreboard import DFIScoreboard


BANKS, ROWS, COLS, BYTES_PER_BEAT = 4, 16, 32, 8


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    for sig in (
        "phy_dfi_rddata", "phy_dfi_rddata_valid",
        "phy_dfi_error", "phy_dfi_error_info", "phy_dfi_crc_alert",
        "phy_dfi_ctrlupd_ack", "phy_dfi_phyupd_req",
        "phy_dfi_training_active", "phy_dfi_training_phase",
        "phy_dfi_parity_check", "phy_dfi_freq_change_ack",
        "phy_dfi_disconnect_req", "phy_dfi_phymstr_req",
    ):
        getattr(dut, sig).value = 0
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
        dfi_version=DFIVersion.V4_0,
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


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dfi_scoreboard_routes_events_test(dut):
    """Scoreboard receives events from 4 distinct areas + on_any sink."""
    await _bring_up(dut)
    _, _, slave = _make_stack(dut)
    _ = DFIMasterMC(dut, dut.dfi_clk)

    # Auto-poll: spawn a coroutine that drains the scoreboard each cycle
    sb = DFIScoreboard(slave)

    error_seen = []
    crc_seen = []
    training_seen = []
    takeover_seen = []
    any_seen = []

    sb.on_error(error_seen.append)
    sb.on_crc(crc_seen.append)
    sb.on_training(training_seen.append)
    sb.on_takeover(takeover_seen.append)
    sb.on_any(lambda area, evt: any_seen.append((area, type(evt).__name__)))

    async def auto_poll():
        while True:
            await RisingEdge(dut.dfi_clk)
            sb.poll()

    cocotb.start_soon(auto_poll())
    await Timer(1, units="ns")

    # ----- Stimulus: pulse 4 different areas -----
    slave.set_error(active=1, info=0xAA)
    await RisingEdge(dut.dfi_clk)
    slave.set_error(active=0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)

    slave.set_crc_alert(active=1)
    await RisingEdge(dut.dfi_clk)
    slave.set_crc_alert(active=0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)

    slave.set_training(active=1, phase=2)   # DQ_TRAINING
    await RisingEdge(dut.dfi_clk)
    slave.set_training(active=0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)

    slave.set_phymstr_req(active=1)
    await RisingEdge(dut.dfi_clk)
    slave.set_phymstr_req(active=0)
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)

    # ----- Final poll to drain any stragglers -----
    sb.poll()

    dut._log.info(f"scoreboard: {sb}")
    dut._log.info(f"report: {sb.report()}")

    # ----- Assertions -----

    assert len(error_seen)    >= 1, "error callback never fired"
    assert len(crc_seen)      >= 1, "crc callback never fired"
    assert len(training_seen) >= 1, "training callback never fired"
    assert len(takeover_seen) >= 1, "takeover callback never fired"

    # Specific payload checks
    assert error_seen[0].code == 0xAA
    assert training_seen[0].phase.value == "dq"
    assert takeover_seen[0].reason == "phy_managed"

    # on_any caught events from all 4 areas
    areas_in_any = {area for (area, _typ) in any_seen}
    assert {"error", "crc", "training", "takeover"} <= areas_in_any, (
        f"on_any missed areas: {areas_in_any}"
    )

    rpt = sb.report()
    assert rpt["error"]    >= 1
    assert rpt["crc"]      >= 1
    assert rpt["training"] >= 1
    assert rpt["takeover"] >= 1
    # Areas we didn't stimulate stay at zero
    assert rpt["update"]      == 0
    assert rpt["ca_parity"]   == 0
    assert rpt["freq_change"] == 0
    assert rpt["disconnect"]  == 0

    dut._log.info("Scoreboard end-to-end routing verified")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_scoreboard_e2e(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_scoreboard_e2e"
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
        module="test_dfi_scoreboard_e2e",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
