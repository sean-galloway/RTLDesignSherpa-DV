# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2: violation injection — proving the referees catch on real wires.

Two checkers, both attacked deliberately through the shim:

  1. **DFIComplianceChecker** (latency windows): compliant handshake
     traffic first (zero violations), then a too-short ctrlupd pulse
     and an unacknowledged phyupd request — each must be flagged.
  2. **DramStateModel** (JEDEC sequencing/timing): the slave is built
     with an all-soft ViolationPolicy so the sim survives, then the
     master injects WR-without-ACT, a tRCD violation, an early PRE
     (tRAS), an ACT to an already-active bank, and a back-to-back ACT
     pair (tRRD). Each named rule must appear in the soft counters.

Until now the suites only proved the absence of false positives; this
test proves the presence of true positives at wire level — the
referee itself is the DUT.
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
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_compliance import (
    ALL_RULES,
    DFIComplianceChecker,
    DFIComplianceParams,
    RULE_TCTRLUPD_MIN,
    RULE_TPHYUPD_RESP,
    RULE_TPHY_WRLAT,
    RULE_TRDDATA_EN,
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
    dut.phy_dfi_alert_n.value = 1  # active low — idles high
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut, policy=None):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory,
                        violation_policy=policy)
    return base, memory, slave


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dfi_compliance_referee_test(dut):
    """Latency-window referee: clean on compliant traffic, then each
    injected breach is flagged."""
    await _bring_up(dut)
    _, _, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    # Handshake rules only — the BFM's write profile is level-driven
    # (wrlat=0) and rddata_en is testbench-managed, so the command-to-
    # enable rules are exercised in the unit tier instead.
    params = DFIComplianceParams(
        tctrlupd_min=2, tctrlupd_max=16, tphyupd_resp=4,
        enabled_rules=frozenset(
            ALL_RULES - {RULE_TPHY_WRLAT, RULE_TRDDATA_EN}
        ),
    )
    chk = DFIComplianceChecker(params)
    cocotb.start_soon(chk.attach(slave.bus, dut.dfi_clk))
    await RisingEdge(dut.dfi_clk)

    # ----- Compliant: ctrlupd pulse of legal width, acked phyupd -----
    master.set_ctrlupd_req(1)
    for _ in range(4):
        await RisingEdge(dut.dfi_clk)
    master.set_ctrlupd_req(0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)

    slave.set_phyupd_req(1)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)
    master.set_phyupd_ack(1)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)
    slave.set_phyupd_req(0)
    master.set_phyupd_ack(0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)

    assert chk.report() == {}, (
        f"false positives on compliant traffic: {chk.report()}"
    )

    # ----- Breach 1: ctrlupd pulse of width 1 (< tctrlupd_min=2) -----
    master.set_ctrlupd_req(1)
    await RisingEdge(dut.dfi_clk)
    master.set_ctrlupd_req(0)
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)
    assert chk.report().get(RULE_TCTRLUPD_MIN, 0) >= 1, (
        f"short ctrlupd pulse not caught: {chk.report()}"
    )

    # ----- Breach 2: phyupd_req never acknowledged -----
    slave.set_phyupd_req(1)
    for _ in range(8):
        await RisingEdge(dut.dfi_clk)
    slave.set_phyupd_req(0)
    for _ in range(2):
        await RisingEdge(dut.dfi_clk)
    assert chk.report().get(RULE_TPHYUPD_RESP, 0) >= 1, (
        f"unacked phyupd not caught: {chk.report()}"
    )

    dut._log.info(f"compliance referee verified: {chk.report()}")


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dram_state_violation_injection_test(dut):
    """JEDEC referee: every injected sequencing/timing breach appears
    in the (all-soft) violation counters."""
    await _bring_up(dut)
    # Demote everything to soft so the sim survives the injections.
    policy = ViolationPolicy(hard=frozenset())
    _, _, slave = _make_stack(dut, policy=policy)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    t = slave.base.timings

    # ----- WR with no ACT (bank 0 idle) -----
    await master.write(bank=0, col=1)
    await master.nop(2)

    # ----- tRCD: ACT then WR immediately (needs tRCD cycles) -----
    await master.activate(bank=1, row=3)
    await master.write(bank=1, col=1)          # way inside tRCD
    await master.nop(t.tRCD_cycles + 2)

    # ----- tRAS: ACT then PRE immediately -----
    await master.activate(bank=2, row=3)
    await master.precharge(bank=2)             # way inside tRAS_min
    await master.nop(2)

    # ----- act_on_active_bank: ACT the already-open bank 1 -----
    await master.activate(bank=1, row=5)
    await master.nop(2)

    # ----- tRRD: back-to-back ACTs to different banks -----
    await master.activate(bank=4, row=1)
    await master.activate(bank=5, row=1)       # inside tRRD
    await master.nop(4)

    soft = slave.dram.policy.soft_violation_counts
    dut._log.info(f"soft violation counters: {soft}")

    for rule in ("no_act_before_wr", "tRCD", "tRAS_min",
                 "act_on_active_bank", "tRRD"):
        assert soft.get(rule, 0) >= 1, (
            f"injected {rule} breach not caught; counters: {soft}"
        )

    dut._log.info("all injected JEDEC breaches caught by the state model")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_violation_injection(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_violation_injection"
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
        module="test_dfi_violation_injection",
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
