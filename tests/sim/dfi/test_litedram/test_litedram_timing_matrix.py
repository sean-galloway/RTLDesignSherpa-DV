# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR2/DDR3/DDR4 LiteDRAM co-sim matrix — configurable timing + gear.

One cocotb module, three pytest runners. Each core runs with:

  - its native gear ratio (DDR2 = 1:2 / 2-phase, DDR3 & DDR4 = 1:4 /
    4-phase), with dfi_freq_ratio driven to the matching spec encoding
    ('b01 = 1:2, 'b10 = 1:4) and verified through a frequency-change
    handshake round-trip;
  - a per-generation JEDEC timing set loaded into the slave's
    DramStateModel (ddr2-650 / ddr3-1600 / ddr4-2400), overridable via
    the DFI_COSIM_TIMING env var — e.g.
    ``DFI_COSIM_TIMING=ddr4-3200 pytest ... -k ddr4`` once such a CSV
    exists in the jedec/ dir;
  - a version-matched envelope (DDR2+v2.1, DDR3+v3.1, DDR4+v4.0).

The test drives ACT/WR/RD/PRE rounds through LiteDRAM's DFII injector
with spacing computed FROM the loaded timing set (converted from DFI
clocks to MC clocks by the gear ratio), then asserts:

  1. the slave saw every command type,
  2. the DramStateModel raised no hard violations (they throw) and
     recorded ZERO soft violations at the configured timing, and
  3. the frequency-change event captured the driven gear encoding.
"""

from __future__ import annotations

import math
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


# ----- Per-core configuration, selected via env by the pytest runner --
CORE_CONFIG = {
    "ddr2": dict(
        n_phases=2, phy_period_ps=5000,
        timing="ddr2-650-mt47h64m16hr",
        version=DFIVersion.V2_1, memory_type=MemoryType.DDR2,
        freq_ratio_code=1,          # 'b01 = 1:2 MC:PHY
    ),
    "ddr3": dict(
        n_phases=4, phy_period_ps=2500,
        timing="ddr3-1600",
        version=DFIVersion.V3_1, memory_type=MemoryType.DDR3,
        freq_ratio_code=2,          # 'b10 = 1:4
    ),
    "ddr4": dict(
        n_phases=4, phy_period_ps=2500,
        timing="ddr4-2400",
        version=DFIVersion.V4_0, memory_type=MemoryType.DDR4,
        freq_ratio_code=2,          # 'b10 = 1:4
    ),
}

# LiteDRAM DFII CSR map — identical layout on all three generated cores.
CSR_SDRAM_DFII_CONTROL = 0x800
PI0_COMMAND       = 0x804
PI0_COMMAND_ISSUE = 0x808
PI0_ADDRESS       = 0x80c
PI0_BADDRESS      = 0x810

CTRL_CKE, CTRL_ODT, CTRL_RESET_N = 0x02, 0x04, 0x08

CMD_CS, CMD_WE, CMD_CAS, CMD_RAS = 0x01, 0x02, 0x04, 0x08
ACTIVATE  = CMD_RAS | CMD_CS
WRITE     = CMD_CAS | CMD_WE | CMD_CS
READ      = CMD_CAS | CMD_CS
PRECHARGE = CMD_RAS | CMD_WE | CMD_CS

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)

_MC_HANDSHAKE_WIRES = (
    "mc_dfi_ctrlupd_req", "mc_dfi_phyupd_ack",
    "mc_dfi_rdlvl_en", "mc_dfi_rdlvl_gate_en", "mc_dfi_wrlvl_en",
    "mc_dfi_parity_in",
    "mc_dfi_init_start", "mc_dfi_freq_ratio", "mc_dfi_frequency",
    "mc_dfi_lp_ctrl_req", "mc_dfi_lp_data_req", "mc_dfi_lp_wakeup",
    "mc_dfi_disconnect_error", "mc_dfi_phymstr_ack",
)


def _cfg():
    return CORE_CONFIG[os.environ["DFI_COSIM_CORE"]]


def _timing_name(cfg) -> str:
    return os.environ.get("DFI_COSIM_TIMING", cfg["timing"])


async def wb_ctrl_write(dut, addr, data, timeout=100):
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


async def _hold(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def inject(dut, command, address=0, bank=0):
    await wb_ctrl_write(dut, PI0_ADDRESS,  address)
    await wb_ctrl_write(dut, PI0_BADDRESS, bank)
    await wb_ctrl_write(dut, PI0_COMMAND,  command)
    await wb_ctrl_write(dut, PI0_COMMAND_ISSUE, 1)


async def _bring_up(dut, cfg, settle_cycles=20):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    cocotb.start_soon(
        Clock(dut.phy_clk, cfg["phy_period_ps"], units="ps").start()
    )
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
    for sig in _MC_HANDSHAKE_WIRES:
        getattr(dut, sig).value = 0
    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


async def _sample_phases(dut, adapter, n_phases):
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(n_phases):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                phase[sig] = int(getattr(dut, f"dfi_p{p}_{sig}").value)
            batch.append(phase)
        adapter.feed(batch)


def _mc_cycles(phy_cycles: int, n_phases: int, margin: int = 2) -> int:
    """DFI-clock (phy) cycle count → MC clock cycles at the gear ratio,
    plus safety margin (adapter pipeline)."""
    return math.ceil(phy_cycles / n_phases) + margin


@cocotb.test(timeout_time=60, timeout_unit="ms")
async def litedram_timing_matrix_test(dut):
    cfg = _cfg()
    timing_name = _timing_name(cfg)
    timings = builtin_timings(timing_name)

    await _bring_up(dut, cfg)

    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16384, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=cfg["version"],
        memory_type=cfg["memory_type"],
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=128, bytes_per_line=8)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=cfg["n_phases"],
        dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_phases(dut, adapter, cfg["n_phases"]))
    await Timer(1, units="ns")

    # Advertise the gear ratio on the spec wire before "init".
    dut.mc_dfi_freq_ratio.value = cfg["freq_ratio_code"]

    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _hold(dut, 10)

    # ----- Timing-aware ACT → WR → RD → PRE rounds -----
    # Spacing derived from the LOADED timing set, converted to MC
    # clocks at this core's gear ratio. Each DFII inject costs several
    # MC cycles of CSR writes on its own; the explicit waits guarantee
    # the JEDEC gaps even if CSR access were instant.
    n = cfg["n_phases"]
    gap_rcd = _mc_cycles(timings.tRCD_cycles, n)
    gap_wr  = _mc_cycles(timings.CWL + timings.BL // 2
                         + timings.tWR_cycles, n)
    gap_wtr = _mc_cycles(timings.CWL + timings.BL // 2
                         + timings.tWTR_cycles, n)
    gap_rtp = _mc_cycles(max(timings.tRTP_cycles, timings.CL), n)
    gap_rp  = _mc_cycles(timings.tRP_cycles, n)
    gap_rrd = _mc_cycles(timings.tRRD_cycles, n)

    rounds = 4
    for i in range(rounds):
        bank = i % 4
        await inject(dut, ACTIVATE, address=0x10 + i, bank=bank)
        await _hold(dut, gap_rcd)
        await inject(dut, WRITE, address=0x8, bank=bank)
        await _hold(dut, max(gap_wr, gap_wtr))
        await inject(dut, READ, address=0x8, bank=bank)
        await _hold(dut, gap_rtp)
        await inject(dut, PRECHARGE, address=0x400, bank=bank)
        await _hold(dut, max(gap_rp, gap_rrd))

    # ----- Gear-ratio round trip via the freq-change handshake -----
    dut.mc_dfi_init_start.value = 1
    await _hold(dut, 2)
    dut.mc_dfi_init_start.value = 0
    await _hold(dut, 2)

    await _hold(dut, 20)
    dut._log.info(f"[{os.environ['DFI_COSIM_CORE']}] timing={timing_name} "
                  f"gear=1:{n} cmd_counts={dict(slave.cmd_counts)}")

    # ----- 1. Every command type observed -----
    for cmd in (DRAMCommand.ACT, DRAMCommand.WR, DRAMCommand.RD,
                DRAMCommand.PRE):
        assert slave.cmd_counts.get(cmd, 0) >= rounds, (
            f"expected >= {rounds} {cmd}, got "
            f"{slave.cmd_counts.get(cmd, 0)}: {dict(slave.cmd_counts)}"
        )

    # ----- 2. No timing violations at the configured timing set -----
    # Hard violations raise inside the state model (test would have
    # died); soft ones accumulate on the policy.
    soft = slave.dram.policy.soft_violation_counts
    assert not any(soft.values()), (
        f"timing violations at {timing_name}: {soft}"
    )

    # ----- 3. Frequency-change event carries the gear encoding -----
    assert slave.freq_change_events, "init_start pulse produced no event"
    evt = slave.freq_change_events[0]
    assert evt.freq_ratio == cfg["freq_ratio_code"], (
        f"gear encoding mismatch: drove {cfg['freq_ratio_code']}, "
        f"event carried {evt.freq_ratio}"
    )

    dut._log.info(
        f"[{os.environ['DFI_COSIM_CORE']}] matrix point passed: "
        f"timing={timing_name}, gear=1:{n}, zero violations"
    )


# ---------------------------------------------------------------------
# Pytest runners — one per core
# ---------------------------------------------------------------------


def _run_core(core: str, toplevel: str, wrapper: str, core_subdir: str):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, core_subdir, "gateware",
                          "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = f"test_litedram_timing_matrix_{core}"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build",
                             test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(
            log_dir, f"results_{test_name}.xml"),
        "DFI_COSIM_CORE": core,
    }
    if "DFI_COSIM_TIMING" in os.environ:
        extra_env["DFI_COSIM_TIMING"] = os.environ["DFI_COSIM_TIMING"]

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
            os.path.join(litedram_dir, toplevel + ".sv"),
            os.path.join(litedram_dir, wrapper + ".sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi",
                         "dfi_shim.sv"),
        ],
        toplevel=toplevel,
        module="test_litedram_timing_matrix",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )


def test_litedram_timing_matrix_ddr2(request):
    _run_core("ddr2", "litedram_cosim_top_ddr2",
              "litedram_dfi_wrapper_ddr2", "ddr2")


def test_litedram_timing_matrix_ddr3(request):
    _run_core("ddr3", "litedram_cosim_top",
              "litedram_dfi_wrapper", "ddr3")


def test_litedram_timing_matrix_ddr4(request):
    _run_core("ddr4", "litedram_cosim_top_ddr4",
              "litedram_dfi_wrapper_ddr4", "ddr4")
