# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: CA parity (DDR4-specific v3.0 introduction).

Master drives mc_dfi_parity_in (the parity bit it computed); slave
drives phy_dfi_parity_check when the DRAM detected a mismatch. The
behavior emits a CAParityEvent reflecting the received parity bit.
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
    dut.phy_dfi_crc_alert.value = 0
    dut.phy_dfi_ctrlupd_ack.value = 0
    dut.phy_dfi_phyupd_req.value = 0
    dut.phy_dfi_training_active.value = 0
    dut.phy_dfi_training_phase.value = 0
    dut.phy_dfi_parity_check.value = 0
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


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_ca_parity_test(dut):
    """Master drives parity_in=1; slave asserts parity_check; event lands."""
    await _bring_up(dut)
    _, _, slave = _make_stack(dut)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    # Quiet baseline
    for _ in range(5):
        await RisingEdge(dut.dfi_clk)
    assert len(slave.ca_parity_events) == 0

    # MC computed a parity bit; PHY flags a mismatch
    master.set_parity_in(1)
    slave.set_parity_check(active=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    slave.set_parity_check(active=0)
    master.set_parity_in(0)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)

    dut._log.info(f"slave: {slave}")
    assert len(slave.ca_parity_events) >= 1, (
        f"expected ca_parity_events, got {len(slave.ca_parity_events)}"
    )
    evt = slave.ca_parity_events[0]
    assert evt.parity_bit_received == 1, (
        f"expected parity_bit_received=1, got {evt.parity_bit_received}"
    )
    dut._log.info("CA parity end-to-end proof passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_ca_parity(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_ca_parity"
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
        module="test_dfi_ca_parity",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
