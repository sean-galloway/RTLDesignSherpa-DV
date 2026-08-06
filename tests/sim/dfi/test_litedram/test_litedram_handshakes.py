# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LiteDRAM co-sim + spec-verified DFI handshake areas.

LiteDRAM's DFI implements only the command/write/read trio — no
update, status, low-power, alert, training, or PHY-Master wires (the
"LiteDRAM ceiling"). So this test drives the handshake wires from the
testbench side of the shim WHILE the real LiteDRAM MC generates
command traffic through the same slave. What it proves:

  1. The slave's per-version behavior dispatch handles every spec
     handshake area concurrently with live command traffic — no
     interference in either direction.
  2. Version gating is real on real wires: a v2.1 stack must produce
     ZERO events for post-v2.1 areas (alert, PHY Master, disconnect)
     even when those wires wiggle, and must handle the areas v2.1
     actually defines (bidirectional update, dfi_parity_error,
     init_start frequency change).

Handshake wire names are the spec-verified set (dfi_init_start /
dfi_init_complete for frequency change, dfi_alert_n active low,
dfi_disconnect_error, dfi_phymstr_*, dfi_lp_ctrl/data_req, ...).
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
from CocoTBFramework.components.dfi.behaviors import (
    CRCKind,
    FreqChangeProtocol,
    TrainingPhase,
    UpdateState,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


# ----- LiteDRAM DFII CSRs (phase 0), same map as the sibling tests ---
CSR_SDRAM_DFII_CONTROL           = 0x800
CSR_SDRAM_DFII_PI0_COMMAND       = 0x804
CSR_SDRAM_DFII_PI0_COMMAND_ISSUE = 0x808
CSR_SDRAM_DFII_PI0_ADDRESS       = 0x80c
CSR_SDRAM_DFII_PI0_BADDRESS      = 0x810

CKE_ODT_RESETN = (1 << 1) | (1 << 2) | (1 << 3)

CMD_CS  = 1 << 0
CMD_WE  = 1 << 1
CMD_CAS = 1 << 2
CMD_RAS = 1 << 3
ACTIVATE      = CMD_RAS                             | CMD_CS
WRITE         =           CMD_CAS | CMD_WE          | CMD_CS
READ          =           CMD_CAS                   | CMD_CS
PRECHARGE     = CMD_RAS |           CMD_WE          | CMD_CS
MODE_REGISTER = CMD_RAS | CMD_CAS | CMD_WE          | CMD_CS

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)

# MC-side handshake wires the testbench drives directly (there is no
# DFIMasterMC in co-sim — LiteDRAM owns the command path).
_MC_HANDSHAKE_WIRES = (
    "mc_dfi_ctrlupd_req", "mc_dfi_phyupd_ack",
    "mc_dfi_rdlvl_en", "mc_dfi_rdlvl_gate_en", "mc_dfi_wrlvl_en",
    "mc_dfi_parity_in",
    "mc_dfi_init_start", "mc_dfi_freq_ratio", "mc_dfi_frequency",
    "mc_dfi_lp_ctrl_req", "mc_dfi_lp_data_req", "mc_dfi_lp_wakeup",
    "mc_dfi_disconnect_error", "mc_dfi_phymstr_ack",
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


async def inject(dut, command: int, address: int = 0, bank: int = 0) -> None:
    """Stage and issue a single DFII command on phase 0."""
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_ADDRESS,  address)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_BADDRESS, bank)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND,  command)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_PI0_COMMAND_ISSUE, 1)
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
    for sig in _MC_HANDSHAKE_WIRES:
        getattr(dut, sig).value = 0
    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


async def _sample_litedram_4phase(dut, adapter):
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


def _make_stack(dut, version, memory_type):
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16384, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=version,
        memory_type=memory_type,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(num_lines=128, bytes_per_line=8)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_4phase(dut, adapter))
    return base, slave, adapter


async def _background_traffic(dut, rounds: int = 6):
    """Keep LiteDRAM emitting real commands while handshakes run."""
    for i in range(rounds):
        await inject(dut, ACTIVATE, address=0x10 + i, bank=i % 4)
        await inject(dut, WRITE,    address=0x8,      bank=i % 4)
        await inject(dut, READ,     address=0x8,      bank=i % 4)
        await inject(dut, PRECHARGE, address=0x400,   bank=i % 4)


async def _hold(dut, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clk)


@cocotb.test(timeout_time=40, timeout_unit="ms")
async def litedram_handshakes_v4_0_test(dut):
    """Every v4.0 handshake area exercised during live LiteDRAM traffic."""
    await _bring_up(dut)
    base, slave, adapter = _make_stack(
        dut, DFIVersion.V4_0, MemoryType.DDR4,
    )
    await Timer(1, units="ns")
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CKE_ODT_RESETN)
    await _hold(dut, 10)

    traffic = cocotb.start_soon(_background_traffic(dut))

    # ----- Update: MC-initiated (ctrlupd) -----
    dut.mc_dfi_ctrlupd_req.value = 1
    await _hold(dut, 2)
    slave.set_ctrlupd_ack(1)
    await _hold(dut, 2)
    dut.mc_dfi_ctrlupd_req.value = 0
    slave.set_ctrlupd_ack(0)
    await _hold(dut, 2)
    mc_updates = [e for e in slave.update_events
                  if e.initiator == "mc" and e.state == UpdateState.REQUESTED]
    assert mc_updates, "ctrlupd request never became an UpdateEvent"

    # ----- Update: PHY-initiated (phyupd, with type) -----
    slave.set_phyupd_req(1, update_type=2)
    await _hold(dut, 2)
    dut.mc_dfi_phyupd_ack.value = 1
    await _hold(dut, 2)
    slave.set_phyupd_req(0)
    dut.mc_dfi_phyupd_ack.value = 0
    await _hold(dut, 2)
    phy_updates = [e for e in slave.update_events if e.initiator == "phy"]
    assert phy_updates, "phyupd request never became an UpdateEvent"
    assert phy_updates[0].update_type == 2, (
        f"dfi_phyupd_type not captured: {phy_updates[0]}"
    )

    # ----- Frequency change: init_start + indicator, PHY accepts -----
    dut.mc_dfi_frequency.value = 7
    dut.mc_dfi_freq_ratio.value = 2
    dut.mc_dfi_init_start.value = 1
    await _hold(dut, 2)
    assert slave.freq_change_events, "init_start never became a FreqChangeEvent"
    evt = slave.freq_change_events[0]
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.frequency_code == 7, f"dfi_frequency not captured: {evt}"
    assert evt.freq_ratio == 2, f"dfi_freq_ratio not captured: {evt}"

    slave.accept_freq_change()
    await _hold(dut, 2)
    await Timer(1, units="ns")
    assert int(dut.mc_dfi_init_complete.value) == 0, (
        "PHY's acceptance (init_complete de-assert) not visible MC-side"
    )
    dut.mc_dfi_init_start.value = 0
    slave.set_init_complete(1)
    await _hold(dut, 2)

    # ----- Alert (active low): CRC/parity error report -----
    pre = len(slave.crc_events)
    slave.set_alert_n(1)          # pulls the wire LOW
    await _hold(dut, 2)
    slave.set_alert_n(0)
    await _hold(dut, 2)
    assert len(slave.crc_events) > pre, "alert_n low never became a CRCEvent"
    assert slave.crc_events[pre].kind == CRCKind.DRAM_CRC

    # ----- Training: PHY requests read leveling -----
    pre = len(slave.training_events)
    slave.set_rdlvl_req(1)
    await _hold(dut, 2)
    slave.set_rdlvl_req(0)
    await _hold(dut, 2)
    assert len(slave.training_events) > pre, "rdlvl_req never became an event"
    assert slave.training_events[pre].phase == TrainingPhase.READ_LEVELING

    # ----- PHY Master: takeover request + MC grant -----
    pre = len(slave.takeover_events)
    slave.set_phymstr_req(1)
    await _hold(dut, 2)
    dut.mc_dfi_phymstr_ack.value = 1
    await _hold(dut, 2)
    await Timer(1, units="ns")
    assert int(dut.phy_dfi_phymstr_ack.value) == 1, (
        "MC's phymstr grant not visible PHY-side"
    )
    slave.set_phymstr_req(0)
    dut.mc_dfi_phymstr_ack.value = 0
    await _hold(dut, 2)
    assert len(slave.takeover_events) > pre, "phymstr_req never became an event"
    assert slave.takeover_events[pre].reason == "phy_master"

    # ----- Disconnect: MC flags an error disconnect -----
    pre = len(slave.disconnect_events)
    dut.mc_dfi_disconnect_error.value = 1
    await _hold(dut, 2)
    dut.mc_dfi_disconnect_error.value = 0
    await _hold(dut, 2)
    assert len(slave.disconnect_events) > pre, (
        "disconnect_error never became a DisconnectEvent"
    )
    assert slave.disconnect_events[pre].error is True

    # ----- Low power: ctrl-channel request + ack -----
    pre = len(slave.low_power_events)
    dut.mc_dfi_lp_wakeup.value = 5
    dut.mc_dfi_lp_ctrl_req.value = 1
    await _hold(dut, 2)
    slave.set_lp_ack(1)
    await _hold(dut, 2)
    await Timer(1, units="ns")
    assert int(dut.mc_dfi_lp_ack.value) == 1, "lp_ack not visible MC-side"
    dut.mc_dfi_lp_ctrl_req.value = 0
    slave.set_lp_ack(0)
    await _hold(dut, 2)
    assert len(slave.low_power_events) > pre, (
        "lp_ctrl_req never became a LowPowerEvent"
    )
    lp = slave.low_power_events[pre]
    assert lp.channel == "ctrl" and lp.wakeup == 5

    # ----- The command path must have survived all of the above -----
    await traffic
    await _hold(dut, 20)
    dut._log.info(f"slave: {slave}")
    dut._log.info(f"cmd_counts: {dict(slave.cmd_counts)}")
    for cmd in (DRAMCommand.ACT, DRAMCommand.WR, DRAMCommand.RD,
                DRAMCommand.PRE):
        assert slave.cmd_counts.get(cmd, 0) >= 1, (
            f"LiteDRAM traffic lost {cmd} while handshakes ran: "
            f"{dict(slave.cmd_counts)}"
        )

    dut._log.info("v4.0 handshake areas verified during live LiteDRAM traffic")


@cocotb.test(timeout_time=40, timeout_unit="ms")
async def litedram_handshakes_v2_1_gating_test(dut):
    """v2.1 stack: the v2.1-defined areas work; post-v2.1 areas produce
    ZERO events even when their wires wiggle."""
    await _bring_up(dut)
    base, slave, adapter = _make_stack(
        dut, DFIVersion.V2_1, MemoryType.DDR3,
    )
    await Timer(1, units="ns")
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CKE_ODT_RESETN)
    await _hold(dut, 10)

    traffic = cocotb.start_soon(_background_traffic(dut, rounds=3))

    # ----- v2.1 DDR3-DIMM parity: dedicated dfi_parity_error wire -----
    dut.mc_dfi_parity_in.value = 1
    slave.set_parity_error(1)
    await _hold(dut, 2)
    slave.set_parity_error(0)
    dut.mc_dfi_parity_in.value = 0
    await _hold(dut, 2)
    assert slave.ca_parity_events, (
        "v2.1 dfi_parity_error never became a CAParityEvent"
    )
    assert slave.ca_parity_events[0].parity_bit_received == 1

    # ----- v2.1 bidirectional update -----
    slave.set_phyupd_req(1, update_type=1)
    await _hold(dut, 2)
    slave.set_phyupd_req(0)
    await _hold(dut, 2)
    phy_updates = [e for e in slave.update_events if e.initiator == "phy"]
    assert phy_updates, "v2.1 must support PHY-initiated update (it does)"
    assert phy_updates[0].update_type == 1

    # ----- v2.1 basic frequency change -----
    dut.mc_dfi_freq_ratio.value = 1
    dut.mc_dfi_init_start.value = 1
    await _hold(dut, 2)
    dut.mc_dfi_init_start.value = 0
    await _hold(dut, 2)
    assert slave.freq_change_events
    evt = slave.freq_change_events[0]
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.freq_ratio == 1
    # v2.1 has no dfi_frequency indicator to capture
    assert evt.frequency_code is None

    # ----- Post-v2.1 areas: wires wiggle, NO events may appear -----
    slave.set_alert_n(1)
    slave.set_phymstr_req(1)
    dut.mc_dfi_disconnect_error.value = 1
    await _hold(dut, 3)
    slave.set_alert_n(0)
    slave.set_phymstr_req(0)
    dut.mc_dfi_disconnect_error.value = 0
    await _hold(dut, 3)

    assert len(slave.crc_events) == 0, (
        "v2.1 has no CRC/alert concept — event leaked through version gate"
    )
    assert len(slave.takeover_events) == 0, (
        "v2.1 has no PHY Master — event leaked through version gate"
    )
    assert len(slave.disconnect_events) == 0, (
        "v2.1 has no disconnect protocol — event leaked through version gate"
    )

    # ----- Command path unaffected -----
    await traffic
    await _hold(dut, 20)
    dut._log.info(f"cmd_counts: {dict(slave.cmd_counts)}")
    assert slave.cmd_counts.get(DRAMCommand.ACT, 0) >= 1

    dut._log.info("v2.1 version gating verified on real wires")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_handshakes(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")

    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_handshakes"
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
        module="test_litedram_handshakes",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
