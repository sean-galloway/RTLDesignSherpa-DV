# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Medium-stress DFI traffic test via LiteDRAM's DFII per-phase injector.

Exercises the DFISlavePHY across the full DDR3 command spread (ACT,
WR, RD, PRE, REF, MRS) and across **all 4 DFI phases**. Each DFII
per-phase injector (PI0/PI1/PI2/PI3) places commands on its
corresponding DFI phase, so this test also validates that
DFIPhaseAdapter correctly demuxes a 4-phase source into a 1-phase
stream the slave can consume.

Why DFII injection vs. user-port Wishbone:
    LiteDRAM's user-port Wishbone reaches the bank machines through
    a state machine that requires a full JEDEC init sequence (ZQCS,
    MRS to set CL/BL, repeated REF). Without firmware running that
    sequence, the bank machines stay wedged in a pre-init state and
    silently absorb user-port writes without emitting DFI commands.
    The DFII injector bypasses the bank machines entirely and places
    commands directly on the DFI bus — perfect for stressing the
    BFM slave's command-decode coverage without running real init
    firmware.

Coverage:
    - ACT × 4 (one per bank, across 4 phases)
    - WR  × 4 with auto-precharge
    - RD  × 4 with auto-precharge
    - PRE × 4
    - REF × 2
    - MRS × 4 (one per MR)
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
    DFIPhaseAdapter,
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


# CSR map (from generated csr.h)
CSR_DDRCTRL_INIT_DONE  = 0x000
CSR_SDRAM_DFII_CONTROL = 0x800

# Per-phase injector base addresses (from generated csr.h). Stride is
# 0x18 between phases, not 0x10 — LiteDRAM reserves a few extra CSRs
# per phase (RDDATA/WRDATA tap registers).
PI_BASE = {
    0: 0x804,   # PI0_COMMAND
    1: 0x81c,   # PI1_COMMAND
    2: 0x834,   # PI2_COMMAND
    3: 0x84c,   # PI3_COMMAND
}


def pi_addrs(phase: int) -> tuple[int, int, int, int]:
    """Return (COMMAND, COMMAND_ISSUE, ADDRESS, BADDRESS) for a phase."""
    base = PI_BASE[phase]
    return base, base + 4, base + 8, base + 12


CKE_ODT_RESETN = (1 << 1) | (1 << 2) | (1 << 3)

# DFII command bits
CMD_CS  = 1 << 0
CMD_WE  = 1 << 1
CMD_CAS = 1 << 2
CMD_RAS = 1 << 3

# DDR3 command encodings (per JESD79-3F)
ACTIVATE      = CMD_RAS                            | CMD_CS  # 0x9
WRITE         =                    CMD_CAS | CMD_WE | CMD_CS  # 0x7
READ          =                    CMD_CAS         | CMD_CS  # 0x5
PRECHARGE     = CMD_RAS                  | CMD_WE | CMD_CS   # 0xB
AUTO_REFRESH  = CMD_RAS | CMD_CAS                   | CMD_CS  # 0xD
MODE_REGISTER = CMD_RAS | CMD_CAS | CMD_WE          | CMD_CS  # 0xF


# DFI signal names sampled per phase
_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)


async def wb_ctrl_write(dut, addr: int, data: int, timeout: int = 100) -> None:
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


async def inject(
    dut, phase: int, command: int, address: int = 0, bank: int = 0,
) -> None:
    """Stage and issue a single DFII command on the given phase."""
    cmd_addr, issue_addr, adr_addr, bank_addr = pi_addrs(phase)
    await wb_ctrl_write(dut, adr_addr,   address)
    await wb_ctrl_write(dut, bank_addr,  bank)
    await wb_ctrl_write(dut, cmd_addr,   command)
    await wb_ctrl_write(dut, issue_addr, 1)
    # A few cycles of settle so the next command isn't overlapped
    for _ in range(4):
        await RisingEdge(dut.clk)


async def _bring_up(dut, settle_cycles: int = 20):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.phy_clk, 2500, units="ps").start())
    dut.sim_trace.value = 0
    dut.dfi_rstn.value = 1
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


async def _sample_litedram_4phase(dut, adapter):
    """Feed every MC clock — adapter drains at phy_clk = 4× mc_clk."""
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(4):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                handle = getattr(dut, f"dfi_p{p}_{sig}")
                phase[sig] = int(handle.value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=50, timeout_unit="ms")
async def litedram_medium_stress_test(dut):
    """Inject ACT/WR/RD/PRE/REF/MRS across all 4 DFI phases via DFII."""
    await _bring_up(dut)

    # ----- DFI BFM slave stack -----
    # We deliberately use a small address mapping so the MemoryModel
    # can back the entire space — 8 banks × 16 rows × 16 cols × 16 B
    # = 32 KB. The injection script keeps all row/col addresses under
    # 16 so they stay in range.
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=2048, bytes_per_line=16)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_4phase(dut, adapter))
    await Timer(1, units="ns")

    # ----- Unlock the controller -----
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CKE_ODT_RESETN)
    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE,  1)
    for _ in range(20):
        await RisingEdge(dut.clk)

    # Stages ordered to respect JEDEC timing constraints — the slave's
    # DramStateModel enforces tRP, tRCD, tRFC, tRAS, etc. and aborts on
    # any violation. We need bank idleness for REF (so REF goes last,
    # after a full PRE-all). Between major stages we insert generous
    # waits to clear pending timer obligations.

    async def settle(mc_cycles: int) -> None:
        for _ in range(mc_cycles):
            await RisingEdge(dut.clk)

    # ----- Stage 1: MRS on each MR (4× MRS, distributed across phases)
    dut._log.info("=== Stage 1: MRS to each Mode Register ===")
    mr_values = [0x0008, 0x0040, 0x0020, 0x0000]
    for mr_idx, mr_val in enumerate(mr_values):
        await inject(dut, phase=mr_idx % 4, command=MODE_REGISTER,
                     address=mr_val, bank=mr_idx)
    await settle(20)   # tMRD respect

    # ----- Stage 2: PRECHARGE_ALL × 2 (across 2 phases) -----
    dut._log.info("=== Stage 2: PRECHARGE_ALL × 2 ===")
    for p in (0, 2):
        await inject(dut, phase=p, command=PRECHARGE, address=0x400, bank=0)
    await settle(20)   # tRP respect before ACTs

    # ----- Stage 3: ACT round (one per phase, banks 0..3) -----
    dut._log.info("=== Stage 3: ACT × 4 (one per phase, banks 0..3) ===")
    for p in range(4):
        await inject(dut, phase=p, command=ACTIVATE,
                     address=p, bank=p)   # row = p
    await settle(20)   # tRCD respect before column commands

    # ----- Stage 4: WR round (no auto-precharge so banks stay open) -----
    dut._log.info("=== Stage 4: WR × 4 (no AP) ===")
    for p in range(4):
        await inject(dut, phase=p, command=WRITE,
                     address=p, bank=p)   # col = p, addr[10]=0
    await settle(30)   # tWR closeout

    # ----- Stage 5: PRE banks 0..3 then ACT banks 4..7 for RDs -----
    dut._log.info("=== Stage 5a: PRE banks 0..3 ===")
    for p in range(4):
        await inject(dut, phase=p, command=PRECHARGE, address=0, bank=p)
    await settle(20)

    dut._log.info("=== Stage 5b: ACT × 4 banks 4..7 ===")
    for p in range(4):
        await inject(dut, phase=p, command=ACTIVATE,
                     address=p + 4, bank=4 + p)
    await settle(20)

    # ----- Stage 6: RD round (no AP) -----
    dut._log.info("=== Stage 6: RD × 4 (no AP) ===")
    for p in range(4):
        await inject(dut, phase=p, command=READ,
                     address=p, bank=4 + p)
    await settle(50)   # CL + BL closeout

    # ----- Stage 7: PRE banks 4..7 then PRE_ALL × 2 -----
    dut._log.info("=== Stage 7: PRE banks 4..7 + PRE_ALL × 2 ===")
    for p in range(4):
        await inject(dut, phase=p, command=PRECHARGE, address=0, bank=4 + p)
    await settle(20)
    for p in (0, 2):
        await inject(dut, phase=p, command=PRECHARGE, address=0x400, bank=0)
    await settle(20)

    # ----- Stage 8: REF × 2 (all banks idle now) -----
    dut._log.info("=== Stage 8: AUTO_REFRESH × 2 (after full PRE) ===")
    for p in (1, 3):
        await inject(dut, phase=p, command=AUTO_REFRESH, address=0, bank=0)
    await settle(60)   # tRFC respect

    cmd_counts = dict(slave.cmd_counts)
    dut._log.info(f"FINAL cmd_counts: {cmd_counts}")
    dut._log.info(f"adapter: {adapter}")
    dut._log.info(f"slave: {slave}")

    # ----- Assertions: full command spread reached the slave -----
    mrs  = cmd_counts.get(DRAMCommand.MRS, 0)
    act  = cmd_counts.get(DRAMCommand.ACT, 0)
    wr   = cmd_counts.get(DRAMCommand.WR, 0)
    wra  = cmd_counts.get(DRAMCommand.WRA, 0)
    rd   = cmd_counts.get(DRAMCommand.RD, 0)
    rda  = cmd_counts.get(DRAMCommand.RDA, 0)
    pre  = cmd_counts.get(DRAMCommand.PRE, 0)
    prea = cmd_counts.get(DRAMCommand.PREA, 0)
    ref  = cmd_counts.get(DRAMCommand.REF, 0)

    dut._log.info(
        f"Summary: MRS={mrs}, ACT={act}, "
        f"WR={wr}(+{wra}WRA), RD={rd}(+{rda}RDA), "
        f"PRE={pre}(+{prea}PREA), REF={ref}"
    )

    # We expect to see at least one of each major command type.
    assert mrs  >= 4, f"expected ≥4 MRS,  got {mrs}"
    assert act  >= 4, f"expected ≥4 ACT,  got {act}"
    assert (wr + wra) >= 4, f"expected ≥4 WR/WRA, got {wr}+{wra}"
    assert (rd + rda) >= 4, f"expected ≥4 RD/RDA, got {rd}+{rda}"
    assert (pre + prea) >= 6, (
        f"expected ≥6 PRE+PREA (2 PREA + 4 PRE), got {pre}+{prea}"
    )
    assert ref  >= 2, f"expected ≥2 REF, got {ref}"

    # And the adapter should have driven many phases (4 per MC clock,
    # over hundreds of cycles).
    assert adapter.phases_driven >= 200, (
        f"adapter under-fed: phases_driven={adapter.phases_driven}"
    )

    dut._log.info("Medium-stress DFII injection PASSED")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_user_traffic(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_user_traffic"
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
        verilog_sources=[
            os.path.join(litedram_dir, "litedram_cosim_top.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top",
        module="test_litedram_user_traffic",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
