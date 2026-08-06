# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2: self-refresh and power-down over real wires.

CKE-edge commands were decoded by nothing until now — SRE/SRX/PDE/PDX
sat in the DRAMCommand enum with zero drivers. This test exercises:

  1. SRE (REF encoding + CKE falling) → slave counts SRE, model enters
     self-refresh; SRX (CKE rising) → counted, model exits.
  2. tXS enforcement: an ACT immediately after SRX is flagged; an ACT
     after tXS = tRFC + 10 ns is clean.
  3. The v4.0+ rule that a ctrlupd handshake must precede SRX: a v4.0
     stack exiting WITHOUT the handshake gets srx_without_ctrlupd; the
     same exit WITH a handshake during SR is clean; a v2.1 stack is
     exempt from the rule entirely.
  4. PDE/PDX (CKE toggle with the bus deselected) round-trip with an
     open row (active power-down) — legal, counted, no violations.
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
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.dfi.dram_state import ViolationPolicy
from CocoTBFramework.components.shared.memory_model import MemoryModel


BANKS, ROWS, COLS, BYTES_PER_BEAT = 8, 32, 32, 8


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
    dut.phy_dfi_alert_n.value = 1
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut, version):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=version,
        memory_type=MemoryType.DDR3 if version == DFIVersion.V2_1
        else MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    # All-soft so tXS/handshake breaches count instead of aborting.
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory,
                        violation_policy=ViolationPolicy(hard=frozenset()))
    return base, memory, slave


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def dfi_self_refresh_v4_0_test(dut):
    """v4.0: SR round-trips, tXS enforced, pre-SRX ctrlupd required."""
    await _bring_up(dut)
    _, _, slave = _make_stack(dut, DFIVersion.V4_0)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")
    t = slave.base.timings

    # ----- Round 1: SR exit WITHOUT the required ctrlupd handshake ---
    await master.self_refresh_entry()
    await master.nop(20)
    assert slave.cmd_counts.get(DRAMCommand.SRE, 0) == 1
    assert slave.dram.in_self_refresh

    await master.self_refresh_exit()
    await master.nop(2)
    assert slave.cmd_counts.get(DRAMCommand.SRX, 0) == 1
    assert not slave.dram.in_self_refresh
    soft = slave.dram.policy.soft_violation_counts
    assert soft.get("srx_without_ctrlupd", 0) == 1, (
        f"v4.0 SRX without ctrlupd not flagged: {soft}"
    )

    # ----- tXS: ACT immediately after SRX is too early -----
    await master.activate(bank=0, row=1)
    await master.nop(2)
    soft = slave.dram.policy.soft_violation_counts
    assert soft.get("tXS", 0) >= 1, f"early ACT after SRX not flagged: {soft}"
    # Clean up the open row
    await master.nop(t.tRAS_min_cycles + 2)
    await master.precharge(bank=0)
    await master.nop(t.tRP_cycles + 2)

    # ----- Round 2: handshake before SRX → no new violation -----
    await master.self_refresh_entry()
    await master.nop(5)
    master.set_ctrlupd_req(1)
    slave.set_ctrlupd_ack(1)
    await master.nop(3)
    master.set_ctrlupd_req(0)
    slave.set_ctrlupd_ack(0)
    await master.nop(3)
    await master.self_refresh_exit()
    await master.nop(2)
    soft = slave.dram.policy.soft_violation_counts
    assert soft.get("srx_without_ctrlupd", 0) == 1, (
        f"compliant SRX wrongly flagged: {soft}"
    )

    # ----- ACT after a full tXS wait: clean -----
    pre_txs = slave.dram.policy.soft_violation_counts.get("tXS", 0)
    await master.nop(slave.dram.tXS_cycles + 2)
    await master.activate(bank=1, row=1)
    await master.nop(2)
    assert slave.dram.policy.soft_violation_counts.get("tXS", 0) == pre_txs, (
        "ACT after full tXS wait wrongly flagged"
    )

    dut._log.info(f"soft counters: {slave.dram.policy.soft_violation_counts}")
    dut._log.info("v4.0 self-refresh semantics verified on the wire")


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def dfi_powerdown_and_v2_1_exemption_test(dut):
    """PDE/PDX with an open row (active power-down) is legal; the v2.1
    stack is exempt from the pre-SRX ctrlupd rule."""
    await _bring_up(dut)
    _, _, slave = _make_stack(dut, DFIVersion.V2_1)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")
    t = slave.base.timings

    # ----- Active power-down: open a row, PDE, PDX -----
    await master.activate(bank=2, row=7)
    await master.nop(3)
    await master.powerdown_entry()
    await master.nop(10)
    assert slave.cmd_counts.get(DRAMCommand.PDE, 0) == 1
    assert slave.dram.in_powerdown
    await master.powerdown_exit()
    await master.nop(2)
    assert slave.cmd_counts.get(DRAMCommand.PDX, 0) == 1
    assert not slave.dram.in_powerdown

    # No SR/PD violations from the legal sequence
    soft = slave.dram.policy.soft_violation_counts
    for rule in ("sre_with_open_row", "cmd_during_powerdown",
                 "cmd_during_self_refresh"):
        assert soft.get(rule, 0) in (0, None), f"{rule} wrongly flagged"

    # Close the row, then a v2.1 SR round-trip with NO ctrlupd —
    # the v4.0 rule must NOT apply.
    await master.nop(t.tRAS_min_cycles + 2)
    await master.precharge(bank=2)
    await master.nop(t.tRP_cycles + 2)
    await master.self_refresh_entry()
    await master.nop(10)
    await master.self_refresh_exit()
    await master.nop(2)
    soft = slave.dram.policy.soft_violation_counts
    assert soft.get("srx_without_ctrlupd", 0) in (0, None), (
        f"v2.1 stack wrongly held to the v4.0 pre-SRX rule: {soft}"
    )

    dut._log.info("power-down + v2.1 exemption verified on the wire")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_self_refresh_powerdown(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_self_refresh_powerdown"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="dfi_shim",
        module="test_dfi_self_refresh_powerdown",
        sim_build=sim_build,
        extra_env={
            "COCOTB_LOG_LEVEL": "INFO",
            "COCOTB_RESULTS_FILE": os.path.join(
                log_dir, f"results_{test_name}.xml"),
        },
        extra_args=["-Wno-TIMESCALEMOD", "-Wno-UNUSED", "-Wno-DECLFILENAME"],
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
