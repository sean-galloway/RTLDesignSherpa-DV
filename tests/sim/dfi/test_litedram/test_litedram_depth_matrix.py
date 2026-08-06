# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR2/DDR4 depth co-sim: data integrity + handshakes per core.

The DDR3 core has dedicated deep tests (data integrity, user traffic,
handshakes); this module gives the DDR2 and DDR4 cores the same depth
via one env-parameterized cocotb module with two tests:

  1. **Data integrity** — per-core JEDEC init (ported from the smoke
     tests), then DFII WRITE injections with unique 32-bit payloads on
     every phase; the DFISlavePHY's MemoryModel must hold each payload
     at the flat (bank, row, col) address.
  2. **Handshakes** — the version-matched spec areas exercised during
     command traffic, including negative version-gating:
       - DDR2 + v2.1: parity_error, bidirectional update, basic freq
         change; alert_n / phymstr / disconnect wiggles must produce
         ZERO events.
       - DDR4 + v4.0: alert_n → CRC, phymstr takeover, error
         disconnect, low-power request/ack, freq change with the
         dfi_frequency indicator captured.
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
from CocoTBFramework.components.dfi.behaviors import FreqChangeProtocol
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


CORE_CONFIG = {
    "ddr2": dict(
        n_phases=2, phy_period_ps=5000, bytes_per_line=8,
        timing="ddr2-650-mt47h64m16hr",
        version=DFIVersion.V2_1, memory_type=MemoryType.DDR2,
    ),
    "ddr4": dict(
        n_phases=4, phy_period_ps=2500, bytes_per_line=16,
        timing="ddr4-2400",
        version=DFIVersion.V4_0, memory_type=MemoryType.DDR4,
    ),
}

CSR_DDRCTRL_INIT_DONE  = 0x000
CSR_SDRAM_DFII_CONTROL = 0x800

# Per-phase DFII PI register strides differ per generated core (the
# WRDATA CSR width scales with the per-phase data width): the DDR2
# core uses the DDR3-style 0x18 stride, the DDR4 core uses 0x30.
# Source: each core's generated csr.h.
PI_BASE_BY_CORE = {
    "ddr2": {0: 0x804, 1: 0x81c},
    "ddr4": {0: 0x804, 1: 0x834, 2: 0x864, 3: 0x894},
}

CTRL_CKE, CTRL_ODT, CTRL_RESET_N = 0x02, 0x04, 0x08

CMD_CS, CMD_WE, CMD_CAS, CMD_RAS = 0x01, 0x02, 0x04, 0x08
CMD_WRDATA = 0x10
ACTIVATE  = CMD_RAS | CMD_CS
WRITE     = CMD_CAS | CMD_WE | CMD_CS
WRITE_WD  = WRITE | CMD_WRDATA
READ      = CMD_CAS | CMD_CS
PRECHARGE = CMD_RAS | CMD_WE | CMD_CS
REF       = CMD_RAS | CMD_CAS | CMD_CS
MRS       = CMD_RAS | CMD_CAS | CMD_WE | CMD_CS
ZQC       = CMD_WE | CMD_CS

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


def _pi_base(p):
    return PI_BASE_BY_CORE[os.environ["DFI_COSIM_CORE"]][p]


def pi_cmd(p):    return _pi_base(p)
def pi_iss(p):    return _pi_base(p) + 0x04
def pi_adr(p):    return _pi_base(p) + 0x08
def pi_bad(p):    return _pi_base(p) + 0x0c
def pi_wrdat(p):  return _pi_base(p) + 0x10


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


async def _settle(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def _issue(dut, phase, command, address=0, bank=0, wrdata=None,
                 settle=8):
    if wrdata is not None:
        await wb_ctrl_write(dut, pi_wrdat(phase), wrdata)
    await wb_ctrl_write(dut, pi_adr(phase),  address)
    await wb_ctrl_write(dut, pi_bad(phase),  bank)
    await wb_ctrl_write(dut, pi_cmd(phase),  command)
    await wb_ctrl_write(dut, pi_iss(phase),  1)
    await _settle(dut, settle)


async def litedram_ddr2_init(dut):
    """Canonical DDR2 init (ported from the ddr2 smoke test)."""
    await wb_ctrl_write(dut, pi_adr(0), 0x0)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)
    await _issue(dut, 0, PRECHARGE, 0x400, 0)
    await _issue(dut, 0, MRS, 0x000, 3)
    await _issue(dut, 0, MRS, 0x000, 2)
    await _issue(dut, 0, MRS, 0x000, 1)
    await _issue(dut, 0, MRS, 0x532, 0)      # MR0 with DLL reset
    await _settle(dut, 50)
    await _issue(dut, 0, PRECHARGE, 0x400, 0)
    await _issue(dut, 0, REF, 0x000, 0)
    await _issue(dut, 0, REF, 0x000, 0)
    await _issue(dut, 0, MRS, 0x432, 0)      # MR0 normal
    await _settle(dut, 30)
    await _issue(dut, 0, MRS, 0x380, 1)      # EMR1 OCD default
    await _issue(dut, 0, MRS, 0x000, 1)      # EMR1 OCD exit
    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 50)


async def litedram_ddr4_init(dut):
    """Canonical DDR4 init (ported from the ddr4 smoke test)."""
    await wb_ctrl_write(dut, pi_adr(0), 0x0)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 100)
    for addr, bank in ((0x000, 3), (0x000, 6), (0x400, 5), (0x000, 4),
                       (0x200, 2), (0x301, 1), (0x100, 0)):
        await _issue(dut, 0, MRS, addr, bank, settle=20)
    await _settle(dut, 100)
    await _issue(dut, 0, ZQC, 0x400, 0, settle=100)
    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 50)


_INIT = {"ddr2": litedram_ddr2_init, "ddr4": litedram_ddr4_init}


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


def _make_stack(dut, cfg):
    timings = builtin_timings(cfg["timing"])
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=cfg["version"],
        memory_type=cfg["memory_type"],
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    memory = MemoryModel(
        num_lines=8 * 16 * 16, bytes_per_line=cfg["bytes_per_line"],
    )
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=cfg["n_phases"],
        dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_phases(dut, adapter, cfg["n_phases"]))
    return base, mapping, memory, slave, adapter


async def _hold(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


@cocotb.test(timeout_time=120, timeout_unit="ms")
async def litedram_depth_data_integrity_test(dut):
    """DFII writes with unique payloads on every phase; the slave's
    MemoryModel must hold each payload at the derived flat address."""
    core = os.environ["DFI_COSIM_CORE"]
    cfg = _cfg()
    await _bring_up(dut, cfg)
    base, mapping, memory, slave, adapter = _make_stack(dut, cfg)
    await Timer(1, units="ns")

    await _INIT[core](dut)

    n = cfg["n_phases"]
    writes = []
    payload_base = 0xCAFE_0000
    for bank in range(4):
        row = bank + 1
        for phase in range(n):
            col = phase
            payload = payload_base + (bank << 8) + (phase << 4) + col
            writes.append((phase, bank, row, col, payload))

    # ACT each (bank, row) — one per phase slot round-robin
    for bank in range(4):
        await _issue(dut, phase=bank % n, command=ACTIVATE,
                     address=bank + 1, bank=bank)
    await _settle(dut, 20)

    for phase, bank, row, col, payload in writes:
        await _issue(dut, phase=phase, command=WRITE_WD,
                     address=col, bank=bank, wrdata=payload)
    await _settle(dut, 200)

    dut._log.info(f"[{core}] cmd_counts: {dict(slave.cmd_counts)}")
    assert slave.cmd_counts.get(DRAMCommand.ACT, 0) >= 4
    assert slave.cmd_counts.get(DRAMCommand.WR, 0) >= len(writes)
    assert slave.writes_committed >= len(writes), (
        f"expected >= {len(writes)} committed writes, "
        f"got {slave.writes_committed}"
    )

    # The DFII WRDATA CSR is per-phase-data-width wide; LiteDRAM packs
    # CSR words big-endian, so a single 32-bit CSR write lands in the
    # TOP word of a wide bus (DDR4: bits [127:96]) but in the only
    # word of a 32-bit one (DDR2/DDR3). Accept the payload in exactly
    # one 32-bit lane with every other lane zero.
    def _payload_lane(observed: int, want: int, lanes: int):
        found = None
        for i in range(lanes):
            lane = (observed >> (32 * i)) & 0xFFFF_FFFF
            if lane == want:
                if found is not None:
                    return None      # duplicated — treat as mismatch
                found = i
            elif lane != 0:
                return None          # junk in another lane
        return found

    lanes = memory.bytes_per_line * 8 // 32
    mismatches = []
    for phase, bank, row, col, payload in writes:
        flat = mapping.tuple_to_flat(0, bank, row, col)
        byte_addr = flat * memory.bytes_per_line
        observed = memory.bytearray_to_integer(
            memory.read(byte_addr, memory.bytes_per_line)
        )
        if _payload_lane(observed, payload, lanes) is None:
            mismatches.append((bank, row, col, payload, observed))

    for bank, row, col, want, got in mismatches[:4]:
        dut._log.info(f"  MISMATCH bank={bank} row={row} col={col}: "
                      f"want=0x{want:x} got=0x{got:x}")
    assert not mismatches, (
        f"[{core}] {len(mismatches)}/{len(writes)} data mismatches"
    )
    dut._log.info(f"[{core}] data integrity verified for {len(writes)} writes")


@cocotb.test(timeout_time=120, timeout_unit="ms")
async def litedram_depth_handshakes_test(dut):
    """Version-matched handshake areas + negative gating per core."""
    core = os.environ["DFI_COSIM_CORE"]
    cfg = _cfg()
    await _bring_up(dut, cfg)
    base, mapping, memory, slave, adapter = _make_stack(dut, cfg)
    await Timer(1, units="ns")
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                        CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _hold(dut, 10)

    # Light command traffic in the background
    async def traffic():
        for i in range(3):
            await _issue(dut, phase=0, command=ACTIVATE,
                         address=0x10 + i, bank=i, settle=6)
            await _issue(dut, phase=0, command=PRECHARGE,
                         address=0x400, bank=i, settle=6)
    t = cocotb.start_soon(traffic())

    # --- Update: both directions (v2.1 baseline — valid on all) ---
    dut.mc_dfi_ctrlupd_req.value = 1
    await _hold(dut, 2)
    slave.set_ctrlupd_ack(1)
    await _hold(dut, 2)
    dut.mc_dfi_ctrlupd_req.value = 0
    slave.set_ctrlupd_ack(0)
    slave.set_phyupd_req(1, update_type=1)
    await _hold(dut, 2)
    slave.set_phyupd_req(0)
    await _hold(dut, 2)
    initiators = {e.initiator for e in slave.update_events}
    assert {"mc", "phy"} <= initiators, f"update events: {initiators}"

    # --- Frequency change (init_start protocol, all versions) ---
    dut.mc_dfi_frequency.value = 5
    dut.mc_dfi_freq_ratio.value = 1 if core == "ddr2" else 2
    dut.mc_dfi_init_start.value = 1
    await _hold(dut, 2)
    dut.mc_dfi_init_start.value = 0
    await _hold(dut, 2)
    assert slave.freq_change_events
    evt = slave.freq_change_events[0]
    assert evt.protocol == FreqChangeProtocol.BASIC
    if core == "ddr4":
        assert evt.frequency_code == 5   # v4.0 captures the indicator
    else:
        assert evt.frequency_code is None  # v2.1 has no indicator

    if core == "ddr2":
        # --- v2.1: dedicated parity wire works ---
        dut.mc_dfi_parity_in.value = 1
        slave.set_parity_error(1)
        await _hold(dut, 2)
        slave.set_parity_error(0)
        dut.mc_dfi_parity_in.value = 0
        await _hold(dut, 2)
        assert slave.ca_parity_events, "v2.1 parity_error event missing"

        # --- v2.1 gating: post-v2.1 wires must produce NO events ---
        slave.set_alert_n(1)
        slave.set_phymstr_req(1)
        dut.mc_dfi_disconnect_error.value = 1
        await _hold(dut, 3)
        slave.set_alert_n(0)
        slave.set_phymstr_req(0)
        dut.mc_dfi_disconnect_error.value = 0
        await _hold(dut, 3)
        assert len(slave.crc_events) == 0
        assert len(slave.takeover_events) == 0
        assert len(slave.disconnect_events) == 0
    else:
        # --- v4.0: alert, takeover, disconnect, low power all live ---
        slave.set_alert_n(1)
        await _hold(dut, 2)
        slave.set_alert_n(0)
        assert len(slave.crc_events) >= 1

        slave.set_phymstr_req(1)
        await _hold(dut, 2)
        dut.mc_dfi_phymstr_ack.value = 1
        await _hold(dut, 2)
        slave.set_phymstr_req(0)
        dut.mc_dfi_phymstr_ack.value = 0
        assert len(slave.takeover_events) >= 1
        assert slave.takeover_events[0].reason == "phy_master"

        dut.mc_dfi_disconnect_error.value = 1
        await _hold(dut, 2)
        dut.mc_dfi_disconnect_error.value = 0
        await _hold(dut, 2)
        assert len(slave.disconnect_events) >= 1
        assert slave.disconnect_events[0].error is True

        dut.mc_dfi_lp_wakeup.value = 3
        dut.mc_dfi_lp_ctrl_req.value = 1
        await _hold(dut, 2)
        slave.set_lp_ack(1)
        await _hold(dut, 2)
        dut.mc_dfi_lp_ctrl_req.value = 0
        slave.set_lp_ack(0)
        assert len(slave.low_power_events) >= 1
        assert slave.low_power_events[0].wakeup == 3

    await t
    await _hold(dut, 10)
    assert slave.cmd_counts.get(DRAMCommand.ACT, 0) >= 3, (
        "handshakes disturbed the command path"
    )
    dut._log.info(f"[{core}] handshake depth coverage passed")


# ---------------------------------------------------------------------
# Pytest runners
# ---------------------------------------------------------------------


def _run_core(core, toplevel, wrapper, core_subdir):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, core_subdir, "gateware",
                          "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = f"test_litedram_depth_matrix_{core}"
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
        module="test_litedram_depth_matrix",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )


def test_litedram_depth_matrix_ddr2(request):
    _run_core("ddr2", "litedram_cosim_top_ddr2",
              "litedram_dfi_wrapper_ddr2", "ddr2")


def test_litedram_depth_matrix_ddr4(request):
    _run_core("ddr4", "litedram_cosim_top_ddr4",
              "litedram_dfi_wrapper_ddr4", "ddr4")
