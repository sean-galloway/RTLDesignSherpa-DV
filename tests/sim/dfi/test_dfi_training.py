# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: Training interface phase decoding.

Pressure-tests the single-method shape: training_step(bus, state) ->
TrainingEvent | None with the phase carried as data on
TrainingEvent.phase rather than as separate per-phase methods.

Spec-verified wires (v2.1-v4.0): the PHY requests training via the
per-phase dfi_*_req wires (rdlvl / rdlvl_gate / wrlvl); the behavior
maps each wire to its TrainingPhase enum value. (The fabricated
"training_active/training_phase" pair never existed in any spec.)
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
from CocoTBFramework.components.dfi.behaviors import TrainingPhase
from CocoTBFramework.components.dfi.behaviors.v3_1 import DFIv3_1Behavior
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


BANKS, ROWS, COLS, BYTES_PER_BEAT = 4, 16, 32, 8


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    dut.phy_dfi_rddata.value = 0
    dut.phy_dfi_rddata_valid.value = 0
    dut.phy_dfi_error.value = 0
    dut.phy_dfi_error_info.value = 0
    dut.phy_dfi_alert_n.value = 1
    dut.phy_dfi_ctrlupd_ack.value = 0
    dut.phy_dfi_phyupd_req.value = 0
    dut.phy_dfi_rdlvl_req.value = 0
    dut.phy_dfi_rdlvl_gate_req.value = 0
    dut.phy_dfi_wrlvl_req.value = 0
    dut.phy_dfi_rdlvl_resp.value = 0
    dut.phy_dfi_wrlvl_resp.value = 0
    dut.phy_dfi_phyupd_type.value = 0
    dut.phy_dfi_lp_ack.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)


def _make_stack(dut):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=BANKS, num_rows=ROWS, num_cols=COLS,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    assert isinstance(base.behavior, DFIv3_1Behavior)
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dfi_training_phases_test(dut):
    """Walk the PHY-driven request wires (rdlvl / gate / wrlvl); each
    decoded into the right TrainingPhase enum value."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut)
    _ = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    phases_to_test = [
        (slave.set_rdlvl_req, TrainingPhase.READ_LEVELING),
        (slave.set_rdlvl_gate_req, TrainingPhase.GATE_TRAINING),
        (slave.set_wrlvl_req, TrainingPhase.WRITE_LEVELING),
    ]

    pre_count = 0
    for drive, expected_phase in phases_to_test:
        drive(1)
        await RisingEdge(dut.dfi_clk)
        await RisingEdge(dut.dfi_clk)
        drive(0)
        await RisingEdge(dut.dfi_clk)
        await RisingEdge(dut.dfi_clk)

        new_events = list(slave.training_events)[pre_count:]
        assert len(new_events) >= 1, (
            f"{expected_phase}: no event captured"
        )
        assert new_events[0].phase == expected_phase, (
            f"expected {expected_phase}, got {new_events[0].phase}"
        )
        pre_count = len(slave.training_events)

    dut._log.info(f"slave: {slave}")
    dut._log.info("PHY-requested training phases decoded via single method")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_training(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_training"
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
        module="test_dfi_training",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
