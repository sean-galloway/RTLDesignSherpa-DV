# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2 proof-of-life: Frequency change — multi-version protocol decoding.

Exercises both v3.1 (BASIC protocol only) and v4.0 (Ack/NotAck split)
behaviors in the same test binary, demonstrating that the registry
correctly dispatches to the right behavior class per dfi_version.
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
from CocoTBFramework.components.dfi.behaviors import (
    DFIv3_1Behavior,
    DFIv4_0Behavior,
    FreqChangeProtocol,
)
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
    dut.phy_dfi_freq_change_ack.value = 0
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
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=BANKS * ROWS * COLS, bytes_per_line=BYTES_PER_BEAT,
    )
    slave = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    return base, memory, slave


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_freq_change_v3_1_basic_test(dut):
    """v3.1 uses BASIC protocol regardless of the freq_change_protocol field."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut, DFIVersion.V3_1)
    assert isinstance(base.behavior, DFIv3_1Behavior)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    # Drive a request with protocol=1; v3.1 ignores the protocol code
    master.set_freq_change(req=1, protocol=1)
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    master.set_freq_change(req=0)
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)

    assert len(slave.freq_change_events) >= 1
    assert slave.freq_change_events[0].protocol == FreqChangeProtocol.BASIC


@cocotb.test(timeout_time=1, timeout_unit="ms")
async def dfi_freq_change_v4_0_protocol_split_test(dut):
    """v4.0 decodes the protocol field into ACK / NAK variants."""
    await _bring_up(dut)
    base, _, slave = _make_stack(dut, DFIVersion.V4_0)
    assert isinstance(base.behavior, DFIv4_0Behavior)
    master = DFIMasterMC(dut, dut.dfi_clk)
    await Timer(1, units="ns")

    scenarios = [
        (0, FreqChangeProtocol.BASIC),
        (1, FreqChangeProtocol.ACKNOWLEDGED),
        (2, FreqChangeProtocol.NOT_ACKNOWLEDGED),
    ]
    pre_count = 0
    for code, expected_proto in scenarios:
        master.set_freq_change(req=1, protocol=code)
        await RisingEdge(dut.dfi_clk)
        await RisingEdge(dut.dfi_clk)
        master.set_freq_change(req=0, protocol=0)
        await RisingEdge(dut.dfi_clk)
        await RisingEdge(dut.dfi_clk)

        new_events = list(slave.freq_change_events)[pre_count:]
        assert len(new_events) >= 1, f"protocol code {code}: no event"
        assert new_events[0].protocol == expected_proto, (
            f"protocol code {code}: expected {expected_proto}, "
            f"got {new_events[0].protocol}"
        )
        pre_count = len(slave.freq_change_events)

    dut._log.info(f"slave: {slave}")
    dut._log.info("v4.0 protocol-aware freq_change passed")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_freq_change(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_freq_change"
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
        module="test_dfi_freq_change",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
