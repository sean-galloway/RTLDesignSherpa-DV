# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFIMasterMC validation against DDR2-650.

Drives a representative DDR2 command sequence via the master primitive
API and verifies that both the MC-side and PHY-side monitors decode
the same packet stream. Validates the master's wire encoding for the
v2.1 command set used by DDR2: ACT, RD (with and without
auto-precharge), WR (with and without auto-precharge), PRE (per-bank
and all-banks), REF.

DDR2 does **not** have CRC, CA parity, or the v3.0+ training
interface, so this test deliberately exercises only the v2.1 envelope.
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
    DFIMonitor,
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)


BANKS, ROWS, COLS = 4, 32, 32


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


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def ddr2_master_command_set_test(dut):
    """Drive each DDR2 v2.1 command; both monitors decode identically."""
    await _bring_up(dut)

    # DDR2 stack — base built to validate it accepts the (v2.1, DDR2) pair
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
    del base   # not used after construction-validation; here for the assertion

    master = DFIMasterMC(dut, dut.dfi_clk)
    mc_mon  = DFIMonitor(dut, dut.dfi_clk, side="mc", title="MC-mon")
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-mon")
    await Timer(1, units="ns")

    # ----- Drive each DDR2 command once -----

    # 1. ACT bank=1 row=0x10
    await master.activate(bank=1, row=0x10)
    await master.nop(3)

    # 2. RD bank=1 col=0x04
    await master.read(bank=1, col=0x04)
    await master.nop(3)

    # 3. RD with auto-precharge — bank=1 col=0x08
    await master.read(bank=1, col=0x08, auto_precharge=True)
    await master.nop(3)

    # 4. ACT bank=2 row=0x20 (after auto-pre on bank 1)
    await master.activate(bank=2, row=0x20)
    await master.nop(3)

    # 5. WR bank=2 col=0x10
    await master.write(bank=2, col=0x10)
    await master.write_data(data=0xCAFE_BABE_DEAD_BEEF)
    await master.nop(3)

    # 6. WR with auto-precharge — bank=2 col=0x14
    await master.write(bank=2, col=0x14, auto_precharge=True)
    await master.write_data(data=0xFEED_FACE_C0FF_EE00)
    await master.nop(3)

    # 7. PRE single-bank — bank 3 (was never opened; this just tests the wire)
    # Actually skip — PRE on never-opened bank flags a violation. Use a
    # fresh ACT + PRE instead.
    await master.activate(bank=3, row=0x30)
    await master.nop(timings.tRAS_min_cycles)
    await master.precharge(bank=3)
    await master.nop(3)

    # 8. REF (all-bank refresh)
    await master.refresh()
    await master.nop(timings.tRFC_cycles + 2)

    # 9. PRE all-banks — first open a bank
    await master.activate(bank=0, row=0x40)
    await master.nop(timings.tRAS_min_cycles)
    await master.precharge(all_banks=True)
    await master.nop(3)

    # Drain
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)

    dut._log.info(f"MC : {mc_mon}")
    dut._log.info(f"PHY: {phy_mon}")

    # ----- Assertions: counts match, packet streams identical -----

    assert mc_mon.command_count == phy_mon.command_count, (
        f"DDR2 monitor count mismatch: mc={mc_mon.command_count}, "
        f"phy={phy_mon.command_count}"
    )

    # Expected sequence: 5 ACT, 2 RD, 2 WR, 2 PRE, 1 REF = 12 commands.
    # (Each WR sequence is 1 ACT + 1 WR; the PRE all-banks adds another ACT.)
    expected_sequence = [
        DRAMCommand.ACT,        # ACT bank=1 row=0x10
        DRAMCommand.RD,         # RD  bank=1 col=0x04
        DRAMCommand.RD,         # RD  bank=1 col=0x08 (auto-pre)
        DRAMCommand.ACT,        # ACT bank=2 row=0x20
        DRAMCommand.WR,         # WR  bank=2 col=0x10
        DRAMCommand.WR,         # WR  bank=2 col=0x14 (auto-pre)
        DRAMCommand.ACT,        # ACT bank=3 row=0x30
        DRAMCommand.PRE,        # PRE bank 3
        DRAMCommand.REF,
        DRAMCommand.ACT,        # ACT bank=0 row=0x40
        DRAMCommand.PRE,        # PRE all-banks
    ]
    mc_seq = [p.cmd for p in mc_mon.command_q]
    phy_seq = [p.cmd for p in phy_mon.command_q]
    assert mc_seq == expected_sequence, (
        f"DDR2 MC command sequence mismatch:\n"
        f"  got     : {mc_seq}\n"
        f"  expected: {expected_sequence}"
    )
    assert phy_seq == expected_sequence, "DDR2 PHY sequence mismatch"
    assert mc_seq == phy_seq

    # ----- Auto-precharge bit (addr[10]) on the two AP-flagged ops -----
    rd_packets = [p for p in phy_mon.command_q if p.cmd == DRAMCommand.RD]
    assert (rd_packets[0].address >> 10) & 1 == 0, "first RD should not have AP bit"
    assert (rd_packets[1].address >> 10) & 1 == 1, "second RD (auto-pre) should have AP bit"

    wr_packets = [p for p in phy_mon.command_q if p.cmd == DRAMCommand.WR]
    assert (wr_packets[0].address >> 10) & 1 == 0
    assert (wr_packets[1].address >> 10) & 1 == 1

    # ----- All-banks bit on the second PRE -----
    pre_packets = [p for p in phy_mon.command_q if p.cmd == DRAMCommand.PRE]
    assert (pre_packets[0].address >> 10) & 1 == 0, "single-bank PRE clear"
    assert (pre_packets[1].address >> 10) & 1 == 1, "all-banks PRE bit"

    # ----- 2 write-data beats captured per side -----
    assert mc_mon.write_data_count == 2
    assert phy_mon.write_data_count == 2
    assert mc_mon.write_data_q[0].wrdata == 0xCAFE_BABE_DEAD_BEEF
    assert mc_mon.write_data_q[1].wrdata == 0xFEED_FACE_C0FF_EE00

    dut._log.info("DDR2 master command-set validation passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_master_ddr2(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    test_name = "test_dfi_master_ddr2"
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
        module="test_dfi_master_ddr2",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
