# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Smoke test for the LiteDRAM DFI co-sim infrastructure.

Verifies that the wrapper + generated litedram_core compile and elaborate
cleanly under verilator, and that the Wishbone CSR control path is
working by writing the ``init_done`` CSR (address 0x0) and watching the
``init_done`` output go high.

A proper DRAM init sequence (CKE up, mode register writes, ZQ
calibration) is multi-hundred-step firmware-level work — LiteDRAM's
BIOS does it via the ``sdram_init()`` C function. Porting that to
cocotb is a separate task; this test just proves the wrapper +
Wishbone driver infrastructure works. Once init is properly run,
follow-up tests will exercise the DRAM read/write path and tap DFI
into our :class:`DFISlavePHY`.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run


# ---------------------------------------------------------------------
# Minimal Wishbone classic master (CSR control bus)
# ---------------------------------------------------------------------
#
# Drives the ``wb_ctrl_*`` ports on litedram_dfi_wrapper. Classic
# Wishbone (no pipelining): assert cyc+stb, wait for ack, deassert.


async def wb_ctrl_write(dut, addr: int, data: int, timeout: int = 100):
    """Write a 32-bit value to the LiteDRAM CSR bus."""
    dut.wb_ctrl_adr.value   = addr >> 2     # CSR bus is word-addressed
    dut.wb_ctrl_dat_w.value = data
    dut.wb_ctrl_sel.value   = 0xF
    dut.wb_ctrl_cyc.value   = 1
    dut.wb_ctrl_stb.value   = 1
    dut.wb_ctrl_we.value    = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        if int(dut.wb_ctrl_ack.value) == 1:
            break
    else:
        raise TimeoutError(f"wb_ctrl write to 0x{addr:x} never ack'd")
    dut.wb_ctrl_cyc.value = 0
    dut.wb_ctrl_stb.value = 0
    dut.wb_ctrl_we.value  = 0
    await RisingEdge(dut.clk)


async def wb_ctrl_read(dut, addr: int, timeout: int = 100) -> int:
    """Read a 32-bit value from the LiteDRAM CSR bus."""
    dut.wb_ctrl_adr.value = addr >> 2
    dut.wb_ctrl_sel.value = 0xF
    dut.wb_ctrl_cyc.value = 1
    dut.wb_ctrl_stb.value = 1
    dut.wb_ctrl_we.value  = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        if int(dut.wb_ctrl_ack.value) == 1:
            value = int(dut.wb_ctrl_dat_r.value)
            break
    else:
        raise TimeoutError(f"wb_ctrl read from 0x{addr:x} never ack'd")
    dut.wb_ctrl_cyc.value = 0
    dut.wb_ctrl_stb.value = 0
    await RisingEdge(dut.clk)
    return value


# ---------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------


async def _bring_up(dut, settle_cycles: int = 10):
    """Start the clock and tie off all inputs to idle."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    dut.sim_trace.value = 0
    for sig in (
        "user_port_wishbone_0_adr", "user_port_wishbone_0_dat_w",
        "user_port_wishbone_0_sel", "user_port_wishbone_0_cyc",
        "user_port_wishbone_0_stb", "user_port_wishbone_0_we",
        "wb_ctrl_adr", "wb_ctrl_dat_w", "wb_ctrl_sel",
        "wb_ctrl_cyc", "wb_ctrl_stb", "wb_ctrl_we",
        "wb_ctrl_cti", "wb_ctrl_bte",
    ):
        getattr(dut, sig).value = 0

    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


@cocotb.test(timeout_time=10, timeout_unit="ms")
async def wrapper_elaborates_and_wb_ctrl_works_test(dut):
    """Confirm the wrapper builds, the clock ticks, and the Wishbone CSR
    bus accepts a write whose effect is observable on a top-level port.

    Strategy: write 1 to CSR_DDRCTRL_INIT_DONE_ADDR (=0x0). That
    register's storage is the source of the ``init_done`` output, so
    asserting it via the CSR bus makes ``init_done`` go high. This
    proves both elaboration and end-to-end Wishbone driving even
    though we haven't run the real DRAM init sequence.
    """
    await _bring_up(dut)

    # Baseline: init_done starts at 0
    assert int(dut.init_done.value) == 0, "init_done unexpectedly high at start"
    assert int(dut.init_error.value) == 0, "init_error unexpectedly high at start"

    # Write 1 to init_done CSR (address 0x0)
    await wb_ctrl_write(dut, addr=0x0, data=0x1)
    dut._log.info("Wrote 1 to CSR_DDRCTRL_INIT_DONE_ADDR")

    # Allow a few cycles for the storage to update + the output to propagate
    for _ in range(10):
        await RisingEdge(dut.clk)

    assert int(dut.init_done.value) == 1, (
        "init_done did not assert after CSR write — Wishbone path "
        "or CSR address may be wrong"
    )
    dut._log.info("init_done observed high — Wishbone path works")

    # Readback through the CSR bus too
    readback = await wb_ctrl_read(dut, addr=0x0)
    assert readback == 0x1, f"readback 0x{readback:x}, expected 0x1"
    dut._log.info(f"CSR readback = 0x{readback:x}")

    # And verify init_error stayed clean
    assert int(dut.init_error.value) == 0, "init_error went high during the test"


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_smoke(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")
    wrapper_v = os.path.join(litedram_dir, "litedram_dfi_wrapper.sv")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(
            f"Generated LiteDRAM RTL missing: {core_v}\n"
            f"Run tests/sim/rtl/litedram/regen.sh first."
        )

    test_name = "test_litedram_smoke"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
    }

    extra_args = [
        "-Wno-TIMESCALEMOD",
        "-Wno-COMBDLY",
        "-Wno-CASEINCOMPLETE",
        "-Wno-WIDTHEXPAND",
        "-Wno-WIDTHTRUNC",
        "-Wno-UNOPTFLAT",
        "-Wno-CMPCONST",
        "-Wno-UNUSEDSIGNAL",
        "-Wno-UNUSEDPARAM",
        "-Wno-MULTIDRIVEN",
        "-Wno-SELRANGE",
        "-Wno-LATCH",
        "-Wno-DECLFILENAME",
    ]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[wrapper_v, core_v],
        toplevel="litedram_dfi_wrapper",
        module="test_litedram_smoke",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
