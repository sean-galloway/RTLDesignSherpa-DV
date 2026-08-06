# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: DFIPhaseAdapter at gear ratios 1/2/4.

Each test "MC cycle" feeds N phase dicts (some asserting commands,
some idle); the adapter spreads them across N consecutive DFI clock
cycles; our DFISlavePHY observes the resulting 1-phase stream and
tallies commands.

For LiteDRAM co-sim eventually, the feed() driver will be replaced
by a coroutine that samples N-phase RTL signals each MC cycle. The
demux side of the adapter is what's being validated here.
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
    DFIMonitor,
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_phase_adapter import DFIPhaseAdapter
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


BANKS, ROWS, COLS, BYTES_PER_BEAT = 4, 16, 32, 8


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    for sig in (
        "phy_dfi_rddata", "phy_dfi_rddata_valid",
        "phy_dfi_error", "phy_dfi_error_info",
        "phy_dfi_ctrlupd_ack", "phy_dfi_phyupd_req", "phy_dfi_phyupd_type",
        "phy_dfi_rdlvl_req", "phy_dfi_rdlvl_gate_req", "phy_dfi_wrlvl_req",
        "phy_dfi_rdlvl_resp", "phy_dfi_wrlvl_resp",
        "phy_dfi_parity_error", "phy_dfi_init_complete",
        "phy_dfi_lp_ack", "phy_dfi_phymstr_req",
    ):
        getattr(dut, sig).value = 0
    dut.phy_dfi_alert_n.value = 1  # active low — idles high
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_slave_stack(dut):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


# Encodings for the 5 DRAM commands the adapter feeds. (ras_n, cas_n, we_n)
# per JESD79-3F Table 67 — same table the monitor decodes against.
_ACT = {"cs_n": 0, "ras_n": 0, "cas_n": 1, "we_n": 1}
_RD  = {"cs_n": 0, "ras_n": 1, "cas_n": 0, "we_n": 1}
_WR  = {"cs_n": 0, "ras_n": 1, "cas_n": 0, "we_n": 0}
_PRE = {"cs_n": 0, "ras_n": 0, "cas_n": 1, "we_n": 0}
_REF = {"cs_n": 0, "ras_n": 0, "cas_n": 0, "we_n": 1}
_NOP = {}   # adapter idles all signals to deselected (cs_n=1)


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def adapter_1_phase_passthrough_test(dut):
    """Gear ratio 1: adapter is a 1:1 passthrough. One phase per cycle.
    DDR3-1600 tRCD = 11 DFI cycles."""
    await _bring_up(dut)
    _, _, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=1, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    # ACT
    adapter.feed([{**_ACT, "bank": 1, "address": 0x08}])
    # 11 NOPs for tRCD
    for _ in range(11):
        adapter.feed_idle()
    # RD
    adapter.feed([{**_RD, "bank": 1, "address": 0x04}])
    # Drain
    for _ in range(20):
        await RisingEdge(dut.dfi_clk)

    assert slave.cmd_counts[DRAMCommand.ACT] == 1
    assert slave.cmd_counts[DRAMCommand.RD] == 1


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def adapter_2_phase_burst_test(dut):
    """Gear ratio 2: 2 commands per MC cycle. tRCD=11 → 6 MC cycles."""
    await _bring_up(dut)
    _, _, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=2, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    # MC cycle 1: ACT + NOP
    adapter.feed([
        {**_ACT, "bank": 2, "address": 0x0A},
        _NOP,
    ])
    # 6 MC cycles of idle → 12 DFI cycles (>= tRCD=11)
    for _ in range(6):
        adapter.feed_idle()
    # Final MC cycle: RD + NOP
    adapter.feed([
        {**_RD, "bank": 2, "address": 0x08},
        _NOP,
    ])
    for _ in range(20):
        await RisingEdge(dut.dfi_clk)

    assert slave.cmd_counts[DRAMCommand.ACT] == 1
    assert slave.cmd_counts[DRAMCommand.RD] == 1


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def adapter_4_phase_full_burst_test(dut):
    """Gear ratio 4 (LiteDRAM DDR3 on Xilinx 7-series default):
    4 commands per MC cycle, multiple distinct commands within
    one MC cycle. tRCD=11 → 3 MC cycles for spacing."""
    await _bring_up(dut)
    _, _, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=4, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    # MC cycle 1: ACT bank=3 row=0x0F (valid for 16-row geometry) + 3 NOPs
    adapter.feed([
        {**_ACT, "bank": 3, "address": 0x0F},
        _NOP, _NOP, _NOP,
    ])
    # 3 MC cycles idle = 12 DFI cycles >= tRCD=11
    for _ in range(3):
        adapter.feed_idle()
    # MC cycle 5: ACT phase + 3 NOPs, then RD in MC cycle 6
    adapter.feed([
        {**_RD, "bank": 3, "address": 0x00},
        _NOP, _NOP, _NOP,
    ])
    adapter.feed_idle()
    adapter.feed([
        {**_RD, "bank": 3, "address": 0x04},
        _NOP, _NOP, _NOP,
    ])
    # Wait long enough for the adapter to drain its queue + slack.
    # We fed 7 MC cycles × 4 phases = 28 phases; wait 40 DFI cycles.
    for _ in range(40):
        await RisingEdge(dut.dfi_clk)

    # 1 ACT, 2 RDs across the run
    assert slave.cmd_counts[DRAMCommand.ACT] == 1, (
        f"expected 1 ACT, got {slave.cmd_counts[DRAMCommand.ACT]}"
    )
    assert slave.cmd_counts[DRAMCommand.RD] == 2, (
        f"expected 2 RDs, got {slave.cmd_counts[DRAMCommand.RD]}"
    )

    dut._log.info(f"adapter: {adapter}")
    dut._log.info(f"slave: {slave}")
    # Sanity-check the adapter actually demuxed the queue
    assert adapter.phases_driven > 0
    assert adapter.queued_phases == 0   # queue fully drained


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def adapter_rejects_wrong_phase_count_at_runtime(dut):
    """feed() rejects mid-stream gear drift — defends against the kind
    of bug where the test thinks it's at gear ratio 4 but feeds 2 phases."""
    await _bring_up(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=4, dfi_clock=dut.dfi_clk)

    raised = False
    try:
        adapter.feed([_NOP, _NOP])      # 2 phases at gear ratio 4 — wrong
    except ValueError:
        raised = True
    assert raised, "adapter should have rejected the 2-phase feed at gear=4"


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_phase_adapter(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_phase_adapter"
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
    extra_args = ["-Wno-TIMESCALEMOD", "-Wno-UNUSED", "-Wno-DECLFILENAME"]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=verilog_sources,
        toplevel="dfi_shim",
        module="test_dfi_phase_adapter",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
