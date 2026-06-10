# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 sim test: DFIMonitor against the dfi_shim passthrough RTL.

This test wires two DFIMonitor instances — one on the MC-facing port
of dfi_shim, one on the PHY-facing port — and drives a handful of
DFI v2.1 commands directly onto the MC side. Because dfi_shim is a
pure passthrough, both monitors must observe identical packet streams.
That proves:

  - DFIMonitor's cocotb_bus signal binding works for both ``mc_dfi_``
    and ``phy_dfi_`` prefixes
  - The (ras_n, cas_n, we_n) → DRAMCommand decode is correct
  - Per-sub-interface capture queues (command_q, write_data_q,
    read_data_q) populate in the right order

No master/slave BFM yet — the test drives signals directly so we can
land the monitor + shim infrastructure in one focused commit.
"""

from __future__ import annotations

import os

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi import DRAMCommand
from CocoTBFramework.components.dfi.dfi_monitor import DFIMonitor


# ----- Direct signal-level command issue (no master BFM yet) -----


async def _idle(dut):
    """Drive the MC-side bus to deselected idle (CS_n high, no data)."""
    dut.mc_dfi_address.value = 0
    dut.mc_dfi_bank.value = 0
    dut.mc_dfi_cs_n.value = 1
    dut.mc_dfi_ras_n.value = 1
    dut.mc_dfi_cas_n.value = 1
    dut.mc_dfi_we_n.value = 1
    dut.mc_dfi_cke.value = 1
    dut.mc_dfi_odt.value = 0
    dut.mc_dfi_reset_n.value = 1
    dut.mc_dfi_wrdata.value = 0
    dut.mc_dfi_wrdata_en.value = 0
    dut.mc_dfi_wrdata_mask.value = 0
    dut.mc_dfi_rddata_en.value = 0


async def _issue_command(dut, ras_n, cas_n, we_n, *, bank=0, addr=0):
    """Drive a 1-cycle command pulse on the MC side."""
    dut.mc_dfi_cs_n.value = 0
    dut.mc_dfi_ras_n.value = ras_n
    dut.mc_dfi_cas_n.value = cas_n
    dut.mc_dfi_we_n.value = we_n
    dut.mc_dfi_bank.value = bank
    dut.mc_dfi_address.value = addr
    await RisingEdge(dut.dfi_clk)
    # Return to deselected idle next cycle
    dut.mc_dfi_cs_n.value = 1
    dut.mc_dfi_ras_n.value = 1
    dut.mc_dfi_cas_n.value = 1
    dut.mc_dfi_we_n.value = 1


# ----- The actual cocotb test -----


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_shim_dual_monitor_test(dut):
    """Two monitors on a passthrough shim see identical packet streams."""
    # Start clock
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())

    # Initial conditions
    dut.dfi_rstn.value = 0
    await _idle(dut)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)

    # Attach two monitors — one per side of the shim
    mc_mon = DFIMonitor(dut, dut.dfi_clk, side="mc", title="MC-monitor")
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-monitor")

    # Let the monitor coroutines spin up
    await Timer(1, units="ns")

    # --- Stimulus: a representative DFI command sequence ---
    # ACT bank=2, row=0x100
    await _issue_command(dut, ras_n=0, cas_n=1, we_n=1, bank=2, addr=0x100)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    # RD bank=2, col=0x55
    await _issue_command(dut, ras_n=1, cas_n=0, we_n=1, bank=2, addr=0x55)
    await RisingEdge(dut.dfi_clk)

    # WR bank=2, col=0xAA
    await _issue_command(dut, ras_n=1, cas_n=0, we_n=0, bank=2, addr=0xAA)

    # Drive one beat of write data on the WR cycle
    dut.mc_dfi_wrdata.value = 0xDEADBEEFCAFEBABE
    dut.mc_dfi_wrdata_en.value = 1
    dut.mc_dfi_wrdata_mask.value = 0
    await RisingEdge(dut.dfi_clk)
    dut.mc_dfi_wrdata_en.value = 0

    # PRE bank=2
    await _issue_command(dut, ras_n=0, cas_n=1, we_n=0, bank=2, addr=0)
    await RisingEdge(dut.dfi_clk)

    # REF (all banks)
    await _issue_command(dut, ras_n=0, cas_n=0, we_n=1, bank=0, addr=0)
    await RisingEdge(dut.dfi_clk)

    # Drive one beat of read data from the PHY side
    dut.phy_dfi_rddata.value = 0x123456789ABCDEF0
    dut.phy_dfi_rddata_valid.value = 1
    await RisingEdge(dut.dfi_clk)
    dut.phy_dfi_rddata_valid.value = 0

    # Drain
    await _idle(dut)
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)

    # ----- Assertions -----

    dut._log.info(f"MC  monitor: {mc_mon}")
    dut._log.info(f"PHY monitor: {phy_mon}")

    # Both monitors must see the same number of each kind of event
    assert mc_mon.command_count == phy_mon.command_count, (
        f"command count mismatch mc={mc_mon.command_count} phy={phy_mon.command_count}"
    )
    assert mc_mon.write_data_count == phy_mon.write_data_count, (
        f"write count mismatch mc={mc_mon.write_data_count} phy={phy_mon.write_data_count}"
    )
    assert mc_mon.read_data_count == phy_mon.read_data_count, (
        f"read count mismatch mc={mc_mon.read_data_count} phy={phy_mon.read_data_count}"
    )

    # 5 commands: ACT, RD, WR, PRE, REF
    assert mc_mon.command_count == 5, (
        f"expected 5 commands, got mc={mc_mon.command_count}"
    )
    assert mc_mon.write_data_count == 1
    assert mc_mon.read_data_count == 1

    # Commands in order
    expected = [DRAMCommand.ACT, DRAMCommand.RD, DRAMCommand.WR,
                DRAMCommand.PRE, DRAMCommand.REF]
    mc_cmds = [p.cmd for p in mc_mon.command_q]
    phy_cmds = [p.cmd for p in phy_mon.command_q]
    assert mc_cmds == expected, f"MC saw {mc_cmds}, expected {expected}"
    assert phy_cmds == expected, f"PHY saw {phy_cmds}, expected {expected}"

    # Per-packet field-level cross-check (same data crossed the wire)
    for mc_p, phy_p in zip(mc_mon.command_q, phy_mon.command_q):
        assert mc_p.bank == phy_p.bank
        assert mc_p.address == phy_p.address
        assert mc_p.cmd == phy_p.cmd

    assert mc_mon.write_data_q[0].wrdata == phy_mon.write_data_q[0].wrdata
    assert mc_mon.read_data_q[0].rddata == phy_mon.read_data_q[0].rddata

    dut._log.info("DFI shim dual-monitor test passed")


# ----- Pytest runner -----


def test_dfi_shim_dual_monitor(request):
    """Run the dfi_shim_dual_monitor cocotb test against a verilator build."""
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
