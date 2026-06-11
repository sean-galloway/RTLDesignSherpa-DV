# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR2 slave val test exercising DFIPhaseAdapter at multiple gear ratios.

Same shape as ``test_dfi_slave_ddr2.py`` but the DFI source is
:class:`DFIPhaseAdapter` instead of :class:`DFIMasterMC`. This proves
the slave handles incoming commands identically regardless of whether
the source is our master primitive API (gear=1, MC-side BFM) or a
gear-N source (the eventual LiteDRAM-style MC).

LiteDRAM DDR2 defaults to 2-phase DFI (1:2 ratio); we also exercise
gear=1 (degenerate passthrough) and gear=4 (LiteDRAM DDR3 on Xilinx
7-series, useful for cross-checking adapter mechanics under DDR2).
"""

from __future__ import annotations

import os

import cocotb
import pytest
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
    phase_act,
    phase_nop,
    phase_pre,
    phase_rd,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


BANKS, ROWS, COLS, BYTES_PER_BEAT = 4, 32, 32, 8


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


def _make_slave_stack(dut):
    timings = builtin_timings("ddr2-650-mt47h64m16hr")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR2,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


def _fill_mc_cycle(n_phases, *phases):
    """Pad the variadic phase list out to n_phases with NOPs."""
    result = list(phases) + [phase_nop()] * (n_phases - len(phases))
    assert len(result) == n_phases, (
        f"gear={n_phases}: tried to feed {len(result)} phases per MC cycle"
    )
    return result


async def _run_command_sequence(dut, slave, base, adapter, n_phases):
    """Drive ACT → RD → PRE via the gear-N adapter.

    Each MC cycle advances DFI by ``n_phases``; we pad with idle MC
    cycles to meet DDR2-650 timing (tRCD=5, tRAS_min=15). The
    write-data path is deliberately skipped — that test lives in the
    plain 1-phase loopback under tests/sim/dfi/; here we just prove
    the gear adapter delivers commands to the slave at every ratio.
    """
    trcd     = base.timings.tRCD_cycles      # = 5 for DDR2-650
    tras_min = base.timings.tRAS_min_cycles  # = 15

    def _mc_cycles_for(dfi_cycles):
        """Convert a minimum DFI-cycle count into MC cycles at gear N."""
        return max(1, (dfi_cycles + n_phases - 1) // n_phases)

    # ----- ACT bank 1 row 0x05 -----
    adapter.feed(_fill_mc_cycle(n_phases, phase_act(bank=1, row=0x05)))

    # tRCD wait, then RD
    for _ in range(_mc_cycles_for(trcd)):
        adapter.feed_idle()

    # ----- RD bank 1 col 0x10 -----
    adapter.feed(_fill_mc_cycle(n_phases, phase_rd(bank=1, col=0x10)))

    # Wait for tRAS_min before PRE (already past tRCD; total ACT-to-PRE
    # must be >= tRAS_min). Add some slack.
    for _ in range(_mc_cycles_for(tras_min + 5)):
        adapter.feed_idle()

    # ----- PRE bank 1 -----
    adapter.feed(_fill_mc_cycle(n_phases, phase_pre(bank=1)))

    # Drain
    for _ in range(_mc_cycles_for(20)):
        adapter.feed_idle()

    # Run enough DFI cycles for the adapter to fully drain
    for _ in range(60):
        await RisingEdge(dut.dfi_clk)


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def ddr2_slave_gear_1_test(dut):
    await _bring_up(dut)
    base, memory, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=1, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    await _run_command_sequence(dut, slave, base, adapter, n_phases=1)
    assert slave.cmd_counts[DRAMCommand.ACT] == 1
    assert slave.cmd_counts[DRAMCommand.RD] == 1
    assert slave.cmd_counts[DRAMCommand.PRE] == 1


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def ddr2_slave_gear_2_test(dut):
    """LiteDRAM DDR2 native gear ratio."""
    await _bring_up(dut)
    base, memory, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=2, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    await _run_command_sequence(dut, slave, base, adapter, n_phases=2)
    assert slave.cmd_counts[DRAMCommand.ACT] == 1
    assert slave.cmd_counts[DRAMCommand.RD] == 1
    assert slave.cmd_counts[DRAMCommand.PRE] == 1


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def ddr2_slave_gear_4_test(dut):
    """4-phase variant — non-default for DDR2 but proves the adapter
    handles the wider gear ratio. Mirrors what we'd want for DDR3 + Xilinx 7."""
    await _bring_up(dut)
    base, memory, slave = _make_slave_stack(dut)
    adapter = DFIPhaseAdapter(dut, "mc_dfi", n_phases=4, dfi_clock=dut.dfi_clk)
    cocotb.start_soon(adapter.run())
    await Timer(1, units="ns")

    await _run_command_sequence(dut, slave, base, adapter, n_phases=4)
    assert slave.cmd_counts[DRAMCommand.ACT] == 1
    assert slave.cmd_counts[DRAMCommand.RD] == 1
    assert slave.cmd_counts[DRAMCommand.PRE] == 1


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_slave_ddr2_gear(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    test_name = "test_dfi_slave_ddr2_gear"
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
        module="test_dfi_slave_ddr2_gear",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
