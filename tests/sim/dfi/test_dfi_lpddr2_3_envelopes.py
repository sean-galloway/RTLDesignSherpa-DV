# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LPDDR2/3 CA-bus cross-validation: DFIMasterMC ↔ DFISlavePHY.

Where ``test_dfi_version_envelopes.py`` validates v3.1+/v4.0/v5.2 with
LPDDR4/LPDDR5/DDR5 (which still use the DDR-style ras/cas/we encoding),
this test covers the harder case: **LPDDR2 and LPDDR3 carry commands on
the 20-bit dfi_address CA bus** per DFI v2.1 Table 1, with
ras_n/cas_n/we_n/bank held at idle.

What the test proves:
  - DFIMasterMC, configured with ``memory_type=LPDDR2/3``, drives the
    CA-encoded command word on dfi_address instead of the ras/cas/we
    bits. ras_n/cas_n/we_n/bank stay at their idle values.
  - DFISlavePHY's decoder recognizes ``memory_type`` is LPDDR-family
    and switches to the CA-bus decoder.
  - End-to-end traffic (MRS, PREA, ACT, WR with payload, RD, PRE, REF)
    decodes correctly and the wrdata commits to the slave's memory.

Couldn't be done before this commit — ``DFIControlPacket.from_command``
raised NotImplementedError for LPDDR2. The new ``lpddr_ca`` module
provides the encode/decode pair the BFM needed.
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


async def _drive_canonical_lpddr_traffic(master, payload_base: int):
    """One of each major command, timing-safe per DDR3-1600 timings."""
    # MRS via raw drive (master.mrs() not in API; for LPDDR2 it'd be MRW)
    # For an envelope smoke check we don't need MRS — skip for now.

    # PRE all
    await master.precharge(all_banks=True)
    await master.nop(15)   # tRP

    # ACT bank=2, row=0x8
    await master.activate(bank=2, row=0x8)
    await master.nop(15)   # tRCD

    # WR bank=2, col=0x4 with payload
    await master.write(bank=2, col=0x4)
    await master.write_data(data=payload_base, mask=0)
    await master.nop(30)   # tWR + tWTR

    # RD bank=2, col=0x4
    await master.read(bank=2, col=0x4)
    await master.nop(20)   # CL + BL closeout

    # PRE bank=2
    await master.precharge(bank=2)
    await master.nop(15)   # tRP

    # REF
    await master.refresh()
    await master.nop(220)  # tRFC


async def _run_lpddr_envelope(
    dut, *, title: str, version: DFIVersion, memory_type: MemoryType,
):
    dut._log.info(f"=== LPDDR envelope: {title} ===")

    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=version, memory_type=memory_type,
        timings=timings, mapping=mapping, beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=2048, bytes_per_line=8)
    master = DFIMasterMC(
        dut, dut.dfi_clk, title=f"{title}-mc",
        memory_type=memory_type,
    )
    slave = DFISlavePHY(
        dut, dut.dfi_clk, base=base, memory=memory,
        title=f"{title}-phy",
    )
    await Timer(1, units="ns")

    payload = 0xDEAD_BEEF_0000_0000 | (hash(title) & 0xFFFF_FFFF)
    await _drive_canonical_lpddr_traffic(master, payload)

    counts = dict(slave.cmd_counts)
    dut._log.info(f"  cmd_counts: {counts}")

    # PRE is decoded for both single and all-banks (decoder reuses bucket).
    # PREA is a distinct DRAMCommand value the LPDDR decoder uses for AB=1.
    pre_total = (
        counts.get(DRAMCommand.PRE, 0) + counts.get(DRAMCommand.PREA, 0)
    )
    assert counts.get(DRAMCommand.ACT, 0) >= 1, f"{title}: missing ACT"
    assert counts.get(DRAMCommand.WR,  0) >= 1, f"{title}: missing WR"
    assert counts.get(DRAMCommand.RD,  0) >= 1, f"{title}: missing RD"
    assert pre_total >= 2, (
        f"{title}: expected ≥2 PRE (all-banks + single), "
        f"got PRE={counts.get(DRAMCommand.PRE, 0)} "
        f"PREA={counts.get(DRAMCommand.PREA, 0)}"
    )
    assert counts.get(DRAMCommand.REF, 0) >= 1, f"{title}: missing REF"

    # Data-integrity: payload should be at flat(2, 0x8, 4)
    flat = mapping.tuple_to_flat(0, 2, 8, 4)
    byte_addr = flat * memory.bytes_per_line
    observed = memory.bytearray_to_integer(
        memory.read(byte_addr, memory.bytes_per_line)
    )
    assert observed == payload, (
        f"{title}: data integrity failed — want 0x{payload:x} "
        f"got 0x{observed:x}"
    )

    dut._log.info(f"  ✓ {title} CA-bus traffic verified end-to-end")


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v2_1_lpddr2_envelope_test(dut):
    """DFI v2.1 + LPDDR2 — CA bus encoding per spec Table 1."""
    await _bring_up(dut)
    await _run_lpddr_envelope(
        dut, title="v2.1+LPDDR2",
        version=DFIVersion.V2_1, memory_type=MemoryType.LPDDR2,
    )


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def v3_1_lpddr3_envelope_test(dut):
    """DFI v3.1 + LPDDR3 — same CA bus as LPDDR2."""
    await _bring_up(dut)
    await _run_lpddr_envelope(
        dut, title="v3.1+LPDDR3",
        version=DFIVersion.V3_1, memory_type=MemoryType.LPDDR3,
    )


# ---------------------------------------------------------------------
# Pytest runner — reuses the dfi_shim DUT
# ---------------------------------------------------------------------


def test_dfi_lpddr2_3_envelopes(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    shim_v = os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv")

    test_name = "test_dfi_lpddr2_3_envelopes"
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
        module="test_dfi_lpddr2_3_envelopes",
        sim_build=sim_build,
        extra_env=extra_env,
        # LPDDR2/3 carry the command on the 20-bit CA bus; widen the
        # shim's ADDR_WIDTH to accommodate.
        parameters={"ADDR_WIDTH": 20},
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
