# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""End-to-end Tier 2 sim test: DFIMasterMC ⇄ dfi_shim ⇄ DFISlavePHY.

The master writes a few words to a row, then reads them back. The slave
owns a numpy-backed MemoryModel and commits write data after CWL,
serving the read CL cycles after the RD command. A monitor on the PHY
side watches the wire to spot-check the round trip.

This is the first test where the slave's address-mapping, memory
binding, and timing-aware servicing all run end-to-end against real
RTL.
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


# ---------------------------------------------------------------------
# Geometry for tests — small enough to fit in a modest MemoryModel
# ---------------------------------------------------------------------
#
# 4 banks × 32 rows × 32 cols × 8 bytes/beat = 32 KiB total.
# Picked so flat addresses stay inside the MemoryModel byte range.

BANKS = 4
ROWS = 32
COLS = 32
BYTES_PER_BEAT = 8       # 64-bit data path
NUM_LINES = BANKS * ROWS * COLS  # one MemoryModel "line" per DFI beat


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
    """Build the DFIBase chassis + AddressMapping + MemoryModel + Slave."""
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    # MVP loopback runs BL=1 conceptually — one DFI beat per command.
    # Pinning explicitly so the test stays valid when DFIBase's default
    # changes (default now derives from JEDEC BL).
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=NUM_LINES, bytes_per_line=BYTES_PER_BEAT)
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def dfi_write_read_roundtrip_test(dut):
    """Master writes 4 distinct words, reads them back via the slave."""
    await _bring_up(dut)

    master = DFIMasterMC(dut, dut.dfi_clk)
    base, memory, slave = _make_slave_stack(dut)
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-mon")

    # Hold rddata_en high — the MVP master uses it as a "MC is ready to
    # receive" hint; the slave doesn't gate on it but it's good hygiene.
    master.set_rddata_en(1)
    await Timer(1, units="ns")

    cwl = base.timings.CWL
    cl  = base.timings.CL
    trcd = base.timings.tRCD_cycles
    trrd = base.timings.tRRD_cycles

    # ----- Writes -----

    payloads = {
        (1, 0x00): 0x1111_2222_3333_4444,
        (1, 0x01): 0x5555_6666_7777_8888,
        (1, 0x02): 0x9999_AAAA_BBBB_CCCC,
        (1, 0x03): 0xDDDD_EEEE_FFFF_0000,
    }

    # ACT bank=1, row=0x10
    await master.activate(bank=1, row=0x10)
    await master.nop(trcd)

    # Issue 4 WR + write_data pairs spaced by 4 cycles (BL=1 conceptually)
    for (bank, col), data in payloads.items():
        await master.write(bank=bank, col=col)
        # CWL is when the slave expects the data — drive it then
        await master.nop(cwl - 1)
        await master.write_data(data=data)
        await master.nop(2)  # tWTR-ish breathing room

    # Let any in-flight writes drain
    await master.nop(cwl + 4)

    # ----- Reads -----

    # The slave queues each RD for CL cycles, drives rddata for one cycle.
    # The PHY-side monitor picks up rddata + rddata_valid every cycle it
    # fires, so we can read the captured beats off phy_mon.read_data_q.
    expected_reads_pre = phy_mon.read_data_count
    for (bank, col), _ in payloads.items():
        await master.read(bank=bank, col=col)
        # Spacing — needs to be >= CL so the slave's response lands
        # before the next read overwrites it.
        await master.nop(cl + 2)

    # Drain
    await master.nop(cl + 4)

    dut._log.info(f"slave: {slave}")
    dut._log.info(f"phy_mon: {phy_mon}")

    # ----- Assertions -----

    # Slave committed all 4 writes
    assert slave.writes_committed == 4, (
        f"expected 4 writes committed, got {slave.writes_committed}"
    )
    # Slave served all 4 reads
    assert slave.reads_served == 4, (
        f"expected 4 reads served, got {slave.reads_served}"
    )

    # Verify the memory contents directly
    for (bank, col), expected in payloads.items():
        flat = base.mapping.tuple_to_flat(0, bank, 0x10, col)
        byte_addr = flat * BYTES_PER_BEAT
        ba = memory.read(byte_addr, BYTES_PER_BEAT)
        got = memory.bytearray_to_integer(ba)
        assert got == expected, (
            f"memory[bank={bank} col=0x{col:x} flat=0x{flat:x}] "
            f"got 0x{got:x} expected 0x{expected:x}"
        )

    # Verify the monitor captured each read-data beat with the right value.
    # Order is preserved because we never overlap reads.
    captured = list(phy_mon.read_data_q)[expected_reads_pre:]
    assert len(captured) == 4, (
        f"expected 4 captured read beats, got {len(captured)}"
    )
    for (bank, col), expected in payloads.items():
        # Find the next captured beat
        beat = captured.pop(0)
        assert beat.rddata == expected, (
            f"rddata mismatch for bank={bank} col=0x{col:x}: "
            f"captured 0x{beat.rddata:x} expected 0x{expected:x}"
        )

    dut._log.info("End-to-end write/read round-trip passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_loopback(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_loopback"
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
        module="test_dfi_loopback",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
