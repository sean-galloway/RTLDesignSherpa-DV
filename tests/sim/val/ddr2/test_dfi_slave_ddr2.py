# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFISlavePHY validation against DDR2-650 timings.

Targets the Micron MT47H64M16HR-25:H DDR2 part used on the Digilent
FPGA board. Uses the v2.1 DFI envelope (DDR1-3 + LPDDR1-2 era), the
``ddr2-650-mt47h64m16hr`` JEDEC reference, and a shrunk address
geometry that fits in an in-memory test (4 banks × 32 rows × 32 cols
rather than the part's full 8 × 8192 × 1024 — the BFM mechanics are
the same; we're not modeling the full 128 MiB).

End-to-end: master writes 4 distinct words to consecutive columns,
reads them back, verifies that
  - all writes commit to the MemoryModel at the right flat offsets
  - all reads serve the right data
  - the DRAM state model doesn't flag any JEDEC violations
  - the PHY-side monitor captures the read beats in order
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


# Shrunk geometry for in-memory testing; real part is 8 × 8192 × 1024.
BANKS, ROWS, COLS = 4, 32, 32
BYTES_PER_BEAT = 8


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
    timings = builtin_timings("ddr2-650-mt47h64m16hr")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR2,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,   # MVP loopback runs BL=1 conceptually
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def ddr2_slave_write_read_roundtrip_test(dut):
    """Write 4 words to bank 2, read them back, verify the slave's
    MemoryModel and the captured beats."""
    await _bring_up(dut)

    base, memory, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    phy_mon = DFIMonitor(dut, dut.dfi_clk, side="phy", title="PHY-mon")
    master.set_rddata_en(1)
    await Timer(1, units="ns")

    cwl = base.timings.CWL
    cl  = base.timings.CL
    trcd = base.timings.tRCD_cycles

    # DDR2 sanity: CL=5, CWL=4, BL=4 per the JEDEC CSV
    assert base.timings.CL == 5,  f"DDR2-650 CL should be 5, got {base.timings.CL}"
    assert base.timings.CWL == 4, f"DDR2-650 CWL should be 4, got {base.timings.CWL}"
    assert base.timings.BL == 4,  f"DDR2-650 BL should be 4, got {base.timings.BL}"

    # ACT bank=2 row=0x08
    await master.activate(bank=2, row=0x08)
    await master.nop(trcd)

    payloads = {
        0x00: 0x2222_3333_4444_5555,
        0x01: 0x6666_7777_8888_9999,
        0x02: 0xAAAA_BBBB_CCCC_DDDD,
        0x03: 0xEEEE_FFFF_0011_2233,
    }

    # Writes
    for col, data in payloads.items():
        await master.write(bank=2, col=col)
        await master.nop(cwl - 1)
        await master.write_data(data=data)
        await master.nop(2)
    await master.nop(cwl + 4)

    # Reads — capture order in phy_mon.read_data_q
    pre_count = phy_mon.read_data_count
    for col in payloads:
        await master.read(bank=2, col=col)
        await master.nop(cl + 2)
    await master.nop(cl + 4)

    dut._log.info(f"slave: {slave}")
    dut._log.info(f"phy_mon: {phy_mon}")

    # ----- Memory contents per (bank=2, row=0x08, col) -----
    for col, expected in payloads.items():
        flat = base.mapping.tuple_to_flat(0, 2, 0x08, col)
        ba = memory.read(flat * BYTES_PER_BEAT, BYTES_PER_BEAT)
        got = memory.bytearray_to_integer(ba)
        assert got == expected, (
            f"DDR2 memory[bank=2 col=0x{col:x}] got 0x{got:x}, "
            f"expected 0x{expected:x}"
        )

    # ----- Slave statistics -----
    assert slave.writes_committed == 4
    assert slave.reads_served == 4

    # ----- PHY monitor captured the 4 read beats in order -----
    captured = list(phy_mon.read_data_q)[pre_count:]
    assert len(captured) == 4
    for (col, expected), beat in zip(payloads.items(), captured):
        assert beat.rddata == expected, (
            f"DDR2 captured rddata for col=0x{col:x}: "
            f"got 0x{beat.rddata:x}, expected 0x{expected:x}"
        )

    # ----- No JEDEC violations -----
    soft = slave.dram.policy.soft_violation_counts
    assert not soft, f"DDR2 unexpected soft violations: {soft}"

    dut._log.info("DDR2 slave write/read round-trip validated")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_slave_ddr2(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    test_name = "test_dfi_slave_ddr2"
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
        module="test_dfi_slave_ddr2",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
