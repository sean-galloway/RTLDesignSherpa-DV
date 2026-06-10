# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 sim test: DDR3 BL=8 multi-beat round-trip (issue #16).

DDR3-1600 has BL=8 and the canonical DFI v2.1 PHY ratio is K=2 (DFI
data path is 2× the DRAM data path), so each WR / RD command transfers
4 DFI beats to/from consecutive columns. This test verifies:

  - DFIMasterMC.write_burst() drives N beats over N consecutive cycles
  - DFISlavePHY queues N consecutive writes at cols (C, C+1, …, C+N-1)
    starting CWL cycles after the WR command
  - DFISlavePHY drives N consecutive read beats at cols (C, C+1, …)
    starting CL cycles after the RD command
  - DFIMonitor on the PHY side captures all N beats correctly per
    burst
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
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


# 4 banks × 16 rows × 64 cols × 8 bytes/beat = 32 KiB total.
# 64 cols gives us room for several 4-beat bursts per row.
BANKS = 4
ROWS = 16
COLS = 64
BYTES_PER_BEAT = 8
NUM_LINES = BANKS * ROWS * COLS


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    dut.phy_dfi_rddata.value = 0
    dut.phy_dfi_rddata_valid.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_slave_stack(dut):
    timings = builtin_timings("ddr3-1600")  # BL=8 → default beats=4
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
    )
    assert base.beats_per_burst == 4, "expected default beats=4 for DDR3 BL=8"
    memory = MemoryModel(num_lines=NUM_LINES, bytes_per_line=BYTES_PER_BEAT)
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def dfi_bl8_burst_test(dut):
    """Two 4-beat bursts: WR then RD, both at bank=2, starting col=8."""
    await _bring_up(dut)

    master = DFIMasterMC(dut, dut.dfi_clk)
    base, memory, slave = _make_slave_stack(dut)
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-mon")
    master.set_rddata_en(1)
    await Timer(1, units="ns")

    cwl = base.timings.CWL
    cl  = base.timings.CL
    trcd = base.timings.tRCD_cycles
    beats = base.beats_per_burst  # 4

    # Open bank 2, row 0x4
    await master.activate(bank=2, row=0x4)
    await master.nop(trcd)

    # ----- Burst 1: WR @ col=8 with 4 distinct beat values -----
    payloads_a = [0xA0A0_A0A0_0000_0001,
                  0xA0A0_A0A0_0000_0002,
                  0xA0A0_A0A0_0000_0003,
                  0xA0A0_A0A0_0000_0004]
    await master.write(bank=2, col=8)
    await master.nop(cwl - 1)
    await master.write_burst(payloads_a)
    await master.nop(beats + 4)  # tWTR-ish drain

    # ----- Burst 2: WR @ col=16 -----
    payloads_b = [0xB0B0_B0B0_0000_0010,
                  0xB0B0_B0B0_0000_0020,
                  0xB0B0_B0B0_0000_0030,
                  0xB0B0_B0B0_0000_0040]
    await master.write(bank=2, col=16)
    await master.nop(cwl - 1)
    await master.write_burst(payloads_b)
    await master.nop(beats + 6)

    # ----- RD bursts -----
    # The slave queues 4 reads per RD command; the PHY-side monitor
    # captures every beat that comes back on rddata_valid.
    pre_count = phy_mon.read_data_count
    await master.read(bank=2, col=8)
    await master.nop(cl + beats + 4)  # wait for the 4-beat response + slack

    await master.read(bank=2, col=16)
    await master.nop(cl + beats + 4)

    # Drain
    await master.nop(beats + 8)

    dut._log.info(f"slave: {slave}")
    dut._log.info(f"phy_mon: {phy_mon}")

    # ----- Assertions -----

    # 8 writes committed (4 beats × 2 bursts), 8 reads served
    assert slave.writes_committed == 8, (
        f"expected 8 writes committed, got {slave.writes_committed}"
    )
    assert slave.reads_served == 8, (
        f"expected 8 reads served, got {slave.reads_served}"
    )

    # Memory contents: 8 beats at cols 8..11 and 16..19
    expected = {**{8 + i: payloads_a[i] for i in range(4)},
                **{16 + i: payloads_b[i] for i in range(4)}}
    for col, want in expected.items():
        flat = base.mapping.tuple_to_flat(0, 2, 0x4, col)
        ba = memory.read(flat * BYTES_PER_BEAT, BYTES_PER_BEAT)
        got = memory.bytearray_to_integer(ba)
        assert got == want, (
            f"memory[bank=2 col=0x{col:x}] got 0x{got:x} expected 0x{want:x}"
        )

    # PHY monitor saw all 8 read beats in the right order
    captured = [b.rddata for b in list(phy_mon.read_data_q)[pre_count:]]
    expected_seq = payloads_a + payloads_b
    assert captured == expected_seq, (
        f"captured rddata sequence mismatch\n"
        f"  got     : {[hex(x) for x in captured]}\n"
        f"  expected: {[hex(x) for x in expected_seq]}"
    )

    dut._log.info("BL=8 multi-beat round-trip passed (8 writes / 8 reads)")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_bl8(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_bl8"
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
        module="test_dfi_bl8",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
