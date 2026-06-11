# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI tap test: drive LiteDRAM's DFII injector to issue a SET CTRL
command (CKE / ODT / RESET_N), then watch the wrapper's 4-phase DFI
output ports change accordingly. Proves the out-of-module-reference
tap really brings the internal DFI signals out as observable ports.

Doesn't run the full DDR3 init sequence yet (mode register writes
need correctly-formatted bank+address; one step at a time). This
just exercises the SET CONTROL register, which directly maps to
``dfi_pN_cke`` / ``dfi_pN_odt`` / ``dfi_pN_reset_n`` on every phase.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run


# CSR addresses (from generated csr.h)
CSR_DDRCTRL_INIT_DONE     = 0x000
CSR_SDRAM_DFII_CONTROL    = 0x800
# Bits within the CONTROL register
CTRL_SEL      = 0  # 0=software (DFII), 1=hardware (controller drives)
CTRL_CKE      = 1
CTRL_ODT      = 2
CTRL_RESET_N  = 3


async def wb_ctrl_write(dut, addr: int, data: int, timeout: int = 100):
    dut.wb_ctrl_adr.value   = addr >> 2
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


async def _bring_up(dut, settle_cycles: int = 10):
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


def _snapshot_dfi_control(dut) -> dict:
    """Read CKE / ODT / RESET_N from all 4 phases as one snapshot."""
    return {
        f"p{p}_{sig}": int(getattr(dut, f"dfi_p{p}_{sig}").value)
        for p in range(4)
        for sig in ("cke", "odt", "reset_n")
    }


@cocotb.test(timeout_time=10, timeout_unit="ms")
async def dfi_tap_observes_set_ctrl_test(dut):
    """SET CONTROL register changes propagate to all 4 phases of DFI.

    Confirmed-on-first-attempt finding: LiteDRAM's CSR_SDRAM_DFII_CONTROL
    register has a reset value with CKE / ODT / RESET_N all = 1 (the
    "ready to operate" state). So we exercise the tap by writing a
    *different* value and watching the DFI ports change accordingly.
    """
    await _bring_up(dut)

    # Baseline — LiteDRAM resets the CSR with CKE/ODT/RESET_N = 1.
    # This is itself a useful proof: the wrapper's tap correctly shows
    # the *current* state of the DFI bus, including reset defaults.
    pre = _snapshot_dfi_control(dut)
    dut._log.info(f"DFI baseline (CSR reset value):  {pre}")
    for p in range(4):
        assert pre[f"p{p}_cke"]     == 1, f"phase {p} CKE not at reset default"
        assert pre[f"p{p}_odt"]     == 1, f"phase {p} ODT not at reset default"
        assert pre[f"p{p}_reset_n"] == 1, f"phase {p} RESET_N not at reset default"

    # ----- Drive RESET_N low (put DRAM in reset, leave CKE/ODT alone) -----
    ctrl_lowreset = (
        (0 << CTRL_SEL)
        | (1 << CTRL_CKE)
        | (1 << CTRL_ODT)
        | (0 << CTRL_RESET_N)   # change this bit
    )
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, ctrl_lowreset)
    dut._log.info(f"Wrote 0x{ctrl_lowreset:x} to SDRAM_DFII_CONTROL (RESET_N low)")

    for _ in range(20):
        await RisingEdge(dut.clk)

    mid = _snapshot_dfi_control(dut)
    dut._log.info(f"DFI after RESET_N=0:  {mid}")
    for p in range(4):
        assert mid[f"p{p}_reset_n"] == 0, (
            f"phase {p} RESET_N didn't drop after CSR write — DFI tap broken?"
        )
        # CKE and ODT should still be 1
        assert mid[f"p{p}_cke"] == 1
        assert mid[f"p{p}_odt"] == 1

    # ----- Drive everything low (full quiescent state) -----
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, 0)
    dut._log.info("Wrote 0 to SDRAM_DFII_CONTROL (all bits low)")

    for _ in range(20):
        await RisingEdge(dut.clk)

    post = _snapshot_dfi_control(dut)
    dut._log.info(f"DFI after CTRL=0:  {post}")
    for p in range(4):
        assert post[f"p{p}_cke"]     == 0, f"phase {p} CKE didn't go low"
        assert post[f"p{p}_odt"]     == 0, f"phase {p} ODT didn't go low"
        assert post[f"p{p}_reset_n"] == 0, f"phase {p} RESET_N didn't go low"

    dut._log.info("DFI tap verified — CSR writes propagate to all 4 phases")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_dfi_tap(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")
    wrapper_v = os.path.join(litedram_dir, "litedram_dfi_wrapper.sv")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_dfi_tap"
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
        verilog_sources=[wrapper_v, core_v],
        toplevel="litedram_dfi_wrapper",
        module="test_litedram_dfi_tap",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
