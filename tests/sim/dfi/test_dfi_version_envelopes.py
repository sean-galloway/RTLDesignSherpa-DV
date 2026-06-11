# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI version-envelope cross-validation: DFIMasterMC ↔ DFISlavePHY.

This test directly validates that the DFI BFM's version mechanism
(``DFIBase`` + ``SUPPORTED_MEMORY_BY_VERSION`` + per-version behavior
classes) accepts and round-trips traffic for the higher-version
envelopes we can't reach via LiteDRAM:

    - DFI v3.1 + DDR4    (baseline; covered by litedram_ddr4_smoke)
    - DFI v4.0 + LPDDR4  (LPDDR4 added in v4.0; not in LiteDRAM)
    - DFI v5.2 + LPDDR5  (LPDDR5 added in v5.x; not in LiteDRAM)
    - DFI v5.2 + DDR5    (DDR5 added in v5.x; not in LiteDRAM)

Why this test exists:
    LiteDRAM as external reference caps at DDR4 — its ``litedram_gen``
    only emits SDR/DDR2/DDR3/DDR4. To prove the version mechanism
    works for LPDDR4+ and DDR5 we drive the slave with our own master
    BFM through the ``dfi_shim`` 1-phase passthrough. The master is
    version-agnostic (just drives JEDEC encodings on the bus); the
    slave's decoder + envelope check is what we're validating.

What the test does:
    For each envelope, drive a small canonical sequence (ACT, WR with
    payload, RD, PRE, REF, MRS) and verify the slave decodes each
    command and commits the wrdata to its MemoryModel.
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
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_master_mc import DFIMasterMC
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    dut.phy_dfi_rddata.value = 0
    dut.phy_dfi_rddata_valid.value = 0
    for _ in range(4):
        await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


async def _drive_canonical_traffic(master, payload_base: int):
    """Drive one of each major command + a WR with payload + a RD.

    Inter-command spacing respects DDR3-1600 worst-case JEDEC timings
    (tRP=11, tRCD=11, tRAS=28, tRFC≈208). The slave's DramStateModel
    enforces these uniformly across all version envelopes — same
    timing CSV, different version/memtype packaging.
    """
    # MRS-like (use mode_register encoding via raw command bits)
    await master._drive_command(ras_n=0, cas_n=0, we_n=0, bank=0, address=0x0)
    await master.nop(12)   # tMRD

    # PRE all
    await master.precharge(all_banks=True)
    await master.nop(15)   # tRP

    # ACT bank=2, row=0x8
    await master.activate(bank=2, row=0x8)
    await master.nop(15)   # tRCD

    # WR bank=2, col=0x4 with payload (CWL pipeline before wrdata)
    await master.write(bank=2, col=0x4)
    await master.write_data(data=payload_base, mask=0)
    await master.nop(30)   # tWR + tWTR margin (≥ CWL + BL/2 + tWTR)

    # RD bank=2, col=0x4
    await master.read(bank=2, col=0x4)
    await master.nop(20)   # CL + BL closeout

    # PRE bank=2 (single-bank) — bank still open
    await master.precharge(bank=2)
    await master.nop(15)   # tRP

    # REF — needs all banks idle, which we have post-PRE
    await master.refresh()
    await master.nop(220)  # tRFC


async def _run_envelope(
    dut,
    *,
    title: str,
    version: DFIVersion,
    memory_type: MemoryType,
):
    """Spin up master + slave with the given envelope, drive traffic,
    verify the slave sees and commits each command."""
    dut._log.info(f"=== Envelope: {title} ===")

    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=version,
        memory_type=memory_type,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=2048, bytes_per_line=8)
    master = DFIMasterMC(dut, dut.dfi_clk, title=f"{title}-mc")
    slave  = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory,
                         title=f"{title}-phy")
    await Timer(1, units="ns")

    payload = 0xCAFE_BABE_0000_0000 | (hash(title) & 0xFFFF_FFFF)
    await _drive_canonical_traffic(master, payload)

    counts = dict(slave.cmd_counts)
    dut._log.info(f"  cmd_counts: {counts}")
    dut._log.info(f"  slave: {slave}")

    # Verify slave decoded each primitive type at least once.
    # _CMD_DECODE maps both PRE-bank and PRE-all to DRAMCommand.PRE
    # (addr[10] discriminates internally but the count is shared), so
    # we sum PRE coverage rather than expecting PREA separately.
    assert counts.get(DRAMCommand.MRS,  0) >= 1, f"{title}: missing MRS"
    assert counts.get(DRAMCommand.ACT,  0) >= 1, f"{title}: missing ACT"
    assert counts.get(DRAMCommand.WR,   0) >= 1, f"{title}: missing WR"
    assert counts.get(DRAMCommand.RD,   0) >= 1, f"{title}: missing RD"
    assert counts.get(DRAMCommand.PRE,  0) >= 2, (
        f"{title}: expected ≥2 PRE (all-banks + single), got "
        f"{counts.get(DRAMCommand.PRE, 0)}"
    )
    assert counts.get(DRAMCommand.REF,  0) >= 1, f"{title}: missing REF"

    # And the WR payload should be in the slave's memory at flat(2, 16, 4).
    flat = mapping.tuple_to_flat(0, 2, 8, 4)
    byte_addr = flat * memory.bytes_per_line
    observed = memory.bytearray_to_integer(
        memory.read(byte_addr, memory.bytes_per_line)
    )
    assert observed == payload, (
        f"{title}: data integrity broken — want 0x{payload:x} "
        f"got 0x{observed:x}"
    )

    dut._log.info(f"  ✓ {title} envelope verified end-to-end")


# Each envelope gets its own @cocotb.test() so the DUT/signals reset
# between runs. cocotb-test runs them in sequence within one sim_build.


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v3_1_ddr4_envelope_test(dut):
    """V3.1 + DDR4 — baseline (also covered by LiteDRAM)."""
    await _bring_up(dut)
    await _run_envelope(
        dut, title="v3.1+DDR4",
        version=DFIVersion.V3_1, memory_type=MemoryType.DDR4,
    )


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v4_0_lpddr4_envelope_test(dut):
    """V4.0 + LPDDR4 — beyond LiteDRAM's reach."""
    await _bring_up(dut)
    await _run_envelope(
        dut, title="v4.0+LPDDR4",
        version=DFIVersion.V4_0, memory_type=MemoryType.LPDDR4,
    )


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v5_2_lpddr5_envelope_test(dut):
    """V5.2 + LPDDR5 — top of current support."""
    await _bring_up(dut)
    await _run_envelope(
        dut, title="v5.2+LPDDR5",
        version=DFIVersion.V5_2, memory_type=MemoryType.LPDDR5,
    )


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v5_2_ddr5_envelope_test(dut):
    """V5.2 + DDR5."""
    await _bring_up(dut)
    await _run_envelope(
        dut, title="v5.2+DDR5",
        version=DFIVersion.V5_2, memory_type=MemoryType.DDR5,
    )


# ---------------------------------------------------------------------
# Pytest runner — reuses the existing dfi_shim DUT
# ---------------------------------------------------------------------


def test_dfi_version_envelopes(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    shim_v = os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv")

    test_name = "test_dfi_version_envelopes"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
    }
    extra_args = [
        "-Wno-TIMESCALEMOD", "-Wno-COMBDLY", "-Wno-CASEINCOMPLETE",
        "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-Wno-UNOPTFLAT",
        "-Wno-CMPCONST", "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM",
        "-Wno-MULTIDRIVEN", "-Wno-SELRANGE", "-Wno-LATCH",
        "-Wno-DECLFILENAME",
    ]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[shim_v],
        toplevel="dfi_shim",
        module="test_dfi_version_envelopes",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
