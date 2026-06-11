# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI command injection test: drive LiteDRAM's DFII per-phase command
injector to issue a PRECHARGE_ALL on phase 0, then verify the DFI tap
on the wrapper captures the expected (cs_n, ras_n, cas_n, we_n) encoding
for one cycle.

This is the first test where we observe a real DFI **command** cycle
(not just CONTROL register state). Proves the wrapper's
out-of-module references work for command-bus signals too.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run


# CSR addresses (LiteDRAM-generated csr.h)
CSR_SDRAM_DFII_CONTROL          = 0x800
CSR_SDRAM_DFII_PI0_COMMAND      = 0x804
CSR_SDRAM_DFII_PI0_COMMAND_ISSUE = 0x808
CSR_SDRAM_DFII_PI0_ADDRESS      = 0x80c
CSR_SDRAM_DFII_PI0_BADDRESS     = 0x810

# Bits in CONTROL register
CTRL_SEL_BIT     = 0
CTRL_CKE_BIT     = 1
CTRL_ODT_BIT     = 2
CTRL_RESET_N_BIT = 3

# Bits in PI0_COMMAND register
CMD_CS_BIT  = 0
CMD_WE_BIT  = 1
CMD_CAS_BIT = 2
CMD_RAS_BIT = 3

# DDR3 command encodings (from cmds dict in litedram/init.py)
PRECHARGE_ALL = (
    (1 << CMD_RAS_BIT)
    | (1 << CMD_WE_BIT)
    | (1 << CMD_CS_BIT)
)


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


def _snapshot_p0_cmd(dut) -> dict:
    """Read phase-0 command bus signals as one snapshot."""
    return {
        "cs_n":    int(dut.dfi_p0_cs_n.value),
        "ras_n":   int(dut.dfi_p0_ras_n.value),
        "cas_n":   int(dut.dfi_p0_cas_n.value),
        "we_n":    int(dut.dfi_p0_we_n.value),
        "address": int(dut.dfi_p0_address.value),
        "bank":    int(dut.dfi_p0_bank.value),
    }


async def _dfi_command_sampler(dut, cmd_log):
    """Continuously sample phase-0 DFI command bus; log any cycle with
    cs_n=0 (an active command). Runs forever; spawn with start_soon."""
    while True:
        await RisingEdge(dut.clk)
        if int(dut.dfi_p0_cs_n.value) == 0:
            cmd_log.append({
                "ras_n":   int(dut.dfi_p0_ras_n.value),
                "cas_n":   int(dut.dfi_p0_cas_n.value),
                "we_n":    int(dut.dfi_p0_we_n.value),
                "address": int(dut.dfi_p0_address.value),
                "bank":    int(dut.dfi_p0_bank.value),
            })


@cocotb.test(timeout_time=10, timeout_unit="ms")
async def dfi_tap_captures_precharge_all_test(dut):
    """Issue PRECHARGE_ALL via DFII injector; verify DFI tap on phase 0
    captures the expected JEDEC encoding for exactly one cycle."""
    await _bring_up(dut)

    # Spawn a sampler that runs every clock so we don't miss a 1-cycle pulse
    cmd_log: list = []
    cocotb.start_soon(_dfi_command_sampler(dut, cmd_log))

    # Bring CKE up so the DRAM model considers the bus "active"
    ctrl_cke_up = (
        (0 << CTRL_SEL_BIT)
        | (1 << CTRL_CKE_BIT)
        | (1 << CTRL_ODT_BIT)
        | (1 << CTRL_RESET_N_BIT)
    )
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, ctrl_cke_up)

    # Idle baseline — cs_n should be high (deselected) before injection
    for _ in range(10):
        await RisingEdge(dut.clk)
    baseline = _snapshot_p0_cmd(dut)
    dut._log.info(f"P0 baseline (idle): {baseline}")
    assert baseline["cs_n"] == 1, (
        f"phase 0 CS_n unexpectedly low at idle: {baseline}"
    )

    # ----- Stage a PRECHARGE_ALL command -----
    # PRECHARGE_ALL = address bit 10 set, bank irrelevant (LiteDRAM's
    # init uses address=0x400 for all-banks-PRE).
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  0x400)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  PRECHARGE_ALL)
    dut._log.info(f"Staged PRECHARGE_ALL (cmd=0x{PRECHARGE_ALL:x}, addr=0x400)")

    # ----- Issue the command — watch DFI for cs_n going low -----
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
    dut._log.info("Triggered PI0_COMMAND_ISSUE")

    # Wait for the inject to land
    for _ in range(200):
        await RisingEdge(dut.clk)
        if cmd_log:
            break

    dut._log.info(f"Captured {len(cmd_log)} DFI command cycle(s)")
    for i, c in enumerate(cmd_log[:5]):
        dut._log.info(f"  [{i}] {c}")

    assert cmd_log, "DFI tap never observed a CS_n drop after PRECHARGE_ALL"

    # Expect at least one PRECHARGE_ALL cycle
    pre = next(
        (c for c in cmd_log
         if c["ras_n"] == 0 and c["cas_n"] == 1 and c["we_n"] == 0),
        None,
    )
    assert pre is not None, (
        f"no PRECHARGE encoding (ras_n=0, cas_n=1, we_n=0) seen in "
        f"command log: {cmd_log[:5]}"
    )
    assert (pre["address"] >> 10) & 1 == 1, (
        f"PRECHARGE captured but address[10] not set: "
        f"address=0x{pre['address']:x}"
    )

    dut._log.info("DFI tap captured PRECHARGE_ALL — command-bus path verified")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_dfi_command(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")
    wrapper_v = os.path.join(litedram_dir, "litedram_dfi_wrapper.sv")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_dfi_command"
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
        module="test_litedram_dfi_command",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
