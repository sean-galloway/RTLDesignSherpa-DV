# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 sim tests: DFIMasterMC + DFIMonitor against the dfi_shim
passthrough RTL (issue #16).

The shim is a pure wire passthrough. A :class:`DFIMasterMC` drives the
MC-facing port via its primitive API (``activate``, ``read``, ``write``,
``write_data``, ``precharge``, ``refresh``). Two :class:`DFIMonitor`
instances — one per shim side — verify the same packet stream lands on
both sides, which proves that:

  - DFIMasterMC's signal binding works and produces correct
    (ras_n, cas_n, we_n) encodings for each primitive
  - DFIMonitor decodes the same wire pattern back to the original
    :class:`DRAMCommand`
  - Per-sub-interface capture queues (command_q / write_data_q /
    read_data_q) populate in the right order on both sides
"""

from __future__ import annotations

import os

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi import DRAMCommand, DFIMonitor
from CocoTBFramework.components.dfi.dfi_master_mc import DFIMasterMC


# ---------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------


async def _bring_up(dut):
    """Start the clock, hold reset for a few cycles, then release."""
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    # PHY-side rddata return path stays at 0 unless a test drives it
    dut.phy_dfi_rddata.value = 0
    dut.phy_dfi_rddata_valid.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


# ---------------------------------------------------------------------
# Test 1: master primitives → both monitors see the same stream
# ---------------------------------------------------------------------


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_master_primitives_test(dut):
    """Drive each primitive once; both monitors see identical packets."""
    await _bring_up(dut)

    master = DFIMasterMC(dut, dut.dfi_clk)
    mc_mon = DFIMonitor(dut, dut.dfi_clk, side="mc", title="MC-monitor")
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-monitor")
    await Timer(1, units="ns")

    # ACT bank=2, row=0x100
    await master.activate(bank=2, row=0x100)
    await master.nop(2)

    # RD bank=2, col=0x55
    await master.read(bank=2, col=0x55)
    await master.nop(1)

    # WR bank=2, col=0xAA + immediate write-data beat
    await master.write(bank=2, col=0xAA)
    await master.write_data(data=0xDEADBEEFCAFEBABE, mask=0)

    # PRE bank=2
    await master.precharge(bank=2)
    await master.nop(1)

    # REF
    await master.refresh()
    await master.nop(1)

    # Drive a read-data beat from the PHY side (no slave BFM yet)
    dut.phy_dfi_rddata.value = 0x123456789ABCDEF0
    dut.phy_dfi_rddata_valid.value = 1
    await RisingEdge(dut.dfi_clk)
    dut.phy_dfi_rddata_valid.value = 0

    # Drain
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)

    dut._log.info(f"MC : {mc_mon}")
    dut._log.info(f"PHY: {phy_mon}")

    # ----- Assertions -----

    assert mc_mon.command_count == phy_mon.command_count == 5, (
        f"command count mismatch: mc={mc_mon.command_count} phy={phy_mon.command_count}"
    )
    assert mc_mon.write_data_count == phy_mon.write_data_count == 1
    assert mc_mon.read_data_count == phy_mon.read_data_count == 1

    expected = [DRAMCommand.ACT, DRAMCommand.RD, DRAMCommand.WR,
                DRAMCommand.PRE, DRAMCommand.REF]
    assert [p.cmd for p in mc_mon.command_q] == expected
    assert [p.cmd for p in phy_mon.command_q] == expected

    # Per-packet cross-check: same data, both sides
    for mc_p, phy_p in zip(mc_mon.command_q, phy_mon.command_q):
        assert (mc_p.bank, mc_p.address, mc_p.cmd) == \
               (phy_p.bank, phy_p.address, phy_p.cmd)
    assert mc_mon.write_data_q[0].wrdata == phy_mon.write_data_q[0].wrdata == 0xDEADBEEFCAFEBABE
    assert mc_mon.read_data_q[0].rddata == phy_mon.read_data_q[0].rddata == 0x123456789ABCDEF0

    dut._log.info("All primitives round-tripped through the shim correctly")


# ---------------------------------------------------------------------
# Test 2: a longer command sequence (open row, walk columns, close)
# ---------------------------------------------------------------------


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_master_sequence_test(dut):
    """ACT → 4 × RD → PRE on bank 3, plus a parallel WR sequence on bank 5."""
    await _bring_up(dut)

    master = DFIMasterMC(dut, dut.dfi_clk)
    mon = DFIMonitor(dut, dut.dfi_clk, side="phy")
    await Timer(1, units="ns")

    # Open bank 3, row 0x200
    await master.activate(bank=3, row=0x200)
    await master.nop(2)
    # Walk columns
    for col in (0x00, 0x10, 0x20, 0x30):
        await master.read(bank=3, col=col)
        await master.nop(1)
    # Close
    await master.precharge(bank=3)
    await master.nop(2)

    # Open bank 5, row 0x300, write 2 beats with auto-precharge on the 2nd WR
    await master.activate(bank=5, row=0x300)
    await master.nop(2)
    await master.write(bank=5, col=0x40)
    await master.write_data(0xAAAAAAAAAAAAAAAA)
    await master.write(bank=5, col=0x80, auto_precharge=True)
    await master.write_data(0xBBBBBBBBBBBBBBBB)
    await master.nop(2)

    for _ in range(5):
        await RisingEdge(dut.dfi_clk)

    # Expect: ACT, RD, RD, RD, RD, PRE, ACT, WR, WR = 9 commands
    cmds = [p.cmd for p in mon.command_q]
    expected = [DRAMCommand.ACT,
                DRAMCommand.RD, DRAMCommand.RD, DRAMCommand.RD, DRAMCommand.RD,
                DRAMCommand.PRE,
                DRAMCommand.ACT,
                DRAMCommand.WR, DRAMCommand.WR]
    assert cmds == expected, f"got {cmds}\nexpected {expected}"
    assert mon.write_data_count == 2
    # Auto-precharge bit is address[10]
    second_wr = [p for p in mon.command_q if p.cmd == DRAMCommand.WR][1]
    assert (second_wr.address >> 10) & 1 == 1, "auto_precharge bit not set"


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_shim_dual_monitor(request):
    """Run both cocotb tests against a verilator build of dfi_shim."""
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_shim_dual_monitor"
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
        module="test_dfi_shim",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
