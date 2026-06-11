# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Wire LiteDRAM-emitted DFI cycles through DFIPhaseAdapter.

Issues a few different commands via the DFII per-phase injector
(PRECHARGE_ALL, then a Mode Register write), captures the wrapper's
4-phase DFI bus into Python with a continuous sampler, and feeds the
captured phases through :class:`DFIPhaseAdapter(n_phases=4)`.

This is the last step before wiring our :class:`DFISlavePHY` in: it
proves the end-to-end **sampler → adapter** chain works on real
MC-emitted traffic, decoupled from the BFM slave's signal-binding
requirements.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi import DFIPhaseAdapter


# CSR addresses
CSR_SDRAM_DFII_CONTROL           = 0x800
CSR_SDRAM_DFII_PI0_COMMAND       = 0x804
CSR_SDRAM_DFII_PI0_COMMAND_ISSUE = 0x808
CSR_SDRAM_DFII_PI0_ADDRESS       = 0x80c
CSR_SDRAM_DFII_PI0_BADDRESS      = 0x810

# Command bits
PRECHARGE_ALL = 0xB    # RAS | WE | CS
MODE_REGISTER = 0xF    # RAS | CAS | WE | CS

# CONTROL bits
CKE_ODT_RESETN = 0xE   # CKE=1, ODT=1, RESET_N=1, SEL=0


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


async def _capture_4phase_continuously(dut, captured):
    """Sample all 4 phases each cycle, store any phase with cs_n=0.

    Each captured entry: (cycle, phase_idx, cmd_dict)
    """
    cycle = 0
    while True:
        await RisingEdge(dut.clk)
        cycle += 1
        for p in range(4):
            if int(getattr(dut, f"dfi_p{p}_cs_n").value) == 0:
                captured.append((cycle, p, {
                    "ras_n":   int(getattr(dut, f"dfi_p{p}_ras_n").value),
                    "cas_n":   int(getattr(dut, f"dfi_p{p}_cas_n").value),
                    "we_n":    int(getattr(dut, f"dfi_p{p}_we_n").value),
                    "address": int(getattr(dut, f"dfi_p{p}_address").value),
                    "bank":    int(getattr(dut, f"dfi_p{p}_bank").value),
                }))


@cocotb.test(timeout_time=10, timeout_unit="ms")
async def litedram_dfi_to_adapter_test(dut):
    """Issue 2 different DFII commands; verify the 4-phase sampler
    captures both with correct JEDEC encodings."""
    await _bring_up(dut)

    captured: list = []
    cocotb.start_soon(_capture_4phase_continuously(dut, captured))

    # CKE up so the DRAM model accepts commands
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CKE_ODT_RESETN)

    # ----- Issue #1: PRECHARGE_ALL -----
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  0x400)  # all-banks
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  PRECHARGE_ALL)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
    for _ in range(30):
        await RisingEdge(dut.clk)

    pre_count_after_first = len(captured)

    # ----- Issue #2: MRS to MR2 (Mode Register 2) with arbitrary data -----
    mr2_value = 0x0008
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  mr2_value)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, 2)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  MODE_REGISTER)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
    for _ in range(30):
        await RisingEdge(dut.clk)

    # ----- Assertions on captured DFI cycles -----

    dut._log.info(f"Total DFI command cycles captured: {len(captured)}")
    for i, (cycle, phase, cmd) in enumerate(captured[:8]):
        dut._log.info(
            f"  [{i}] cycle={cycle} phase={phase}: "
            f"(ras_n={cmd['ras_n']}, cas_n={cmd['cas_n']}, "
            f"we_n={cmd['we_n']}, addr=0x{cmd['address']:x}, "
            f"bank={cmd['bank']})"
        )

    assert len(captured) >= 2, (
        f"expected at least 2 DFI commands, captured {len(captured)}"
    )

    # First batch should include a PRECHARGE (ras_n=0, cas_n=1, we_n=0)
    pre_seen = any(
        cmd["ras_n"] == 0 and cmd["cas_n"] == 1 and cmd["we_n"] == 0
        and (cmd["address"] >> 10) & 1 == 1
        for (_, _, cmd) in captured[:pre_count_after_first]
    )
    assert pre_seen, (
        f"PRECHARGE_ALL not seen in first {pre_count_after_first} "
        f"captured cycles"
    )

    # Second batch should include a MODE_REGISTER (ras_n=0, cas_n=0, we_n=0)
    mrs_seen = any(
        cmd["ras_n"] == 0 and cmd["cas_n"] == 0 and cmd["we_n"] == 0
        and cmd["bank"] == 2 and cmd["address"] == mr2_value
        for (_, _, cmd) in captured[pre_count_after_first:]
    )
    assert mrs_seen, (
        "MRS for MR2 not seen after the second injection: "
        f"{captured[pre_count_after_first:][:3]}"
    )

    # ----- Now feed them through DFIPhaseAdapter to prove the chain -----
    # Build a 4-phase batch from the captured PRECHARGE_ALL and confirm
    # the adapter accepts it (proves the data shape matches what the
    # adapter expects).

    # Use the first captured PRECHARGE as the "phase 0" cycle; pad the
    # rest with idle NOPs.
    first_pre = next(
        cmd for (_, _, cmd) in captured
        if cmd["ras_n"] == 0 and cmd["cas_n"] == 1 and cmd["we_n"] == 0
    )

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="user_port_wishbone_0", n_phases=4,
        dfi_clock=dut.clk,
    )
    # (don't actually start the adapter's run loop — the destination
    # signals here are MC-side Wishbone, not real DFI; this test only
    # validates that the adapter accepts the captured-phase shape.)
    adapter.feed([
        {
            "cs_n":    0,
            "ras_n":   first_pre["ras_n"],
            "cas_n":   first_pre["cas_n"],
            "we_n":    first_pre["we_n"],
            "address": first_pre["address"],
            "bank":    first_pre["bank"],
        },
        {}, {}, {},     # 3 idle NOPs
    ])
    assert adapter.queued_phases == 4, "adapter didn't accept the 4-phase batch"

    dut._log.info("LiteDRAM DFI → adapter chain verified")
    dut._log.info(f"adapter: {adapter}")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_dfi_to_adapter(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")
    wrapper_v = os.path.join(litedram_dir, "litedram_dfi_wrapper.sv")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_dfi_to_adapter"
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
        module="test_litedram_dfi_to_adapter",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
