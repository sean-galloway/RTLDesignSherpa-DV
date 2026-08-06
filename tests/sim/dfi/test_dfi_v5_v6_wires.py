# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Tier 2: v5.x / v6.0 behavior classes on real wires.

DFIv5_2Behavior and DFIv6_0Behavior were only unit-tested against mock
buses until now. This test runs them against real signals through
dfi_shim_v5 (the DDR5/LPDDR5-era wire set), sampling the mc-side port
through a lightweight bus view — no cocotb_bus binding needed.

Covered per era:

  v5.2: PHY Managed takeover on the RENAMED dfi_phymngd_* wires (and
        deafness to the old phymstr names — there are none here at
        all); frequency change capturing cmd/data split ratios + FSP;
        training raising RemovedInThisVersionError; the disconnect
        flag still live; the ctrlmsg + WCK channels passing through
        the shim both directions.

  v6.0: dfi_alert (renamed, DDR5 polarity) → CRCEvent while the old
        alert_n wire is ignored; dfi_phy_error/_info (renamed) →
        ErrorEvent while the old error wires are ignored; disconnect
        raising RemovedInThisVersionError; the new dfi_sleep wire
        passing through.
"""

from __future__ import annotations

import os

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi.behaviors import (
    DFIv5_2Behavior,
    DFIv6_0Behavior,
    FreqChangeProtocol,
    RemovedInThisVersionError,
)


class _BusView:
    """Present ``<prefix>_<name>`` DUT handles as ``bus.<name>``
    attributes, which is all the behavior classes need."""

    def __init__(self, dut, prefix: str):
        self._dut = dut
        self._prefix = prefix

    def __getattr__(self, name: str):
        try:
            return getattr(self._dut, f"{self._prefix}_{name}")
        except AttributeError as exc:
            raise AttributeError(name) from exc


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 1
    # MC-side drives
    for sig in (
        "mc_dfi_init_start", "mc_dfi_cmd_freq_ratio",
        "mc_dfi_data_freq_ratio", "mc_dfi_freq_fsp", "mc_dfi_frequency",
        "mc_dfi_sleep", "mc_dfi_2n_mode", "mc_dfi_phymngd_ack",
        "mc_dfi_disconnect_error", "mc_dfi_ctrlmsg_req", "mc_dfi_ctrlmsg",
        "mc_dfi_ctrlmsg_data", "mc_dfi_wck_en", "mc_dfi_wck_toggle",
        "mc_dfi_wck_cs", "mc_dfi_lp_ctrl_req", "mc_dfi_lp_data_req",
        "mc_dfi_lp_ctrl_wakeup", "mc_dfi_lp_data_wakeup",
    ):
        getattr(dut, sig).value = 0
    # PHY-side drives
    for sig in (
        "phy_dfi_phymngd_req", "phy_dfi_phymngd_cs_state",
        "phy_dfi_phymngd_state_sel", "phy_dfi_phymngd_type",
        "phy_dfi_ctrlmsg_ack", "phy_dfi_error", "phy_dfi_error_info",
        "phy_dfi_phy_error", "phy_dfi_phy_error_info",
        "phy_dfi_lp_ctrl_ack", "phy_dfi_lp_data_ack",
    ):
        getattr(dut, sig).value = 0
    dut.phy_dfi_init_complete.value = 1
    dut.phy_dfi_alert_n.value = 1     # active low — idles high
    dut.phy_dfi_alert.value = 1       # DDR5 ALERT_n polarity — idles high
    for _ in range(3):
        await RisingEdge(dut.dfi_clk)


async def _edge(dut, n=1):
    for _ in range(n):
        await RisingEdge(dut.dfi_clk)
    await Timer(1, units="ns")


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dfi_v5_2_wire_semantics_test(dut):
    await _bring_up(dut)
    b = DFIv5_2Behavior()
    mc = _BusView(dut, "mc_dfi")

    # ----- PHY Managed takeover on the renamed wires -----
    dut.phy_dfi_phymngd_req.value = 1
    dut.phy_dfi_phymngd_type.value = 2
    dut.phy_dfi_phymngd_state_sel.value = 1
    await _edge(dut)
    evt = b.phy_takeover(mc, None)
    assert evt is not None, "phymngd_req not sampled on real wires"
    assert evt.reason == "phy_managed"
    assert evt.takeover_type == 2
    assert evt.state_sel == 1
    # MC grants; visible PHY-side through the shim
    dut.mc_dfi_phymngd_ack.value = 1
    await _edge(dut)
    assert int(dut.phy_dfi_phymngd_ack.value) == 1
    dut.phy_dfi_phymngd_req.value = 0
    dut.mc_dfi_phymngd_ack.value = 0
    await _edge(dut)
    assert b.phy_takeover(mc, None) is None

    # ----- Frequency change: split ratios + FSP + 6-bit indicator ----
    dut.mc_dfi_frequency.value = 33
    dut.mc_dfi_cmd_freq_ratio.value = 0
    dut.mc_dfi_data_freq_ratio.value = 3     # 'b11 = 1:8 (new in 5.2)
    dut.mc_dfi_freq_fsp.value = 1
    dut.mc_dfi_init_start.value = 1
    await _edge(dut)
    evt = b.freq_change(mc, None)
    assert evt is not None
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.frequency_code == 33
    assert evt.cmd_freq_ratio == 0
    assert evt.data_freq_ratio == 3
    assert evt.freq_fsp == 1
    dut.mc_dfi_init_start.value = 0
    await _edge(dut)

    # ----- Training: interface removed in v5.x -----
    with pytest.raises(RemovedInThisVersionError):
        b.training_step(mc, None)

    # ----- Disconnect still live in v5.x -----
    dut.mc_dfi_disconnect_error.value = 1
    await _edge(dut)
    # PHY-side view samples the flag through the shim
    phy = _BusView(dut, "phy_dfi")
    evt = b.disconnect_request(phy, None)
    assert evt is not None and evt.error is True
    dut.mc_dfi_disconnect_error.value = 0
    await _edge(dut)

    # ----- ctrlmsg channel passthrough (5.1+) -----
    dut.mc_dfi_ctrlmsg.value = 0xA5
    dut.mc_dfi_ctrlmsg_data.value = 0xBEEF
    dut.mc_dfi_ctrlmsg_req.value = 1
    await _edge(dut)
    assert int(dut.phy_dfi_ctrlmsg.value) == 0xA5
    assert int(dut.phy_dfi_ctrlmsg_data.value) == 0xBEEF
    assert int(dut.phy_dfi_ctrlmsg_req.value) == 1
    dut.phy_dfi_ctrlmsg_ack.value = 1
    await _edge(dut)
    assert int(dut.mc_dfi_ctrlmsg_ack.value) == 1
    dut.mc_dfi_ctrlmsg_req.value = 0
    dut.phy_dfi_ctrlmsg_ack.value = 0

    # ----- WCK wires passthrough (LPDDR5) -----
    dut.mc_dfi_wck_en.value = 0x3
    dut.mc_dfi_wck_toggle.value = 0x5
    dut.mc_dfi_wck_cs.value = 0x1
    await _edge(dut)
    assert int(dut.phy_dfi_wck_en.value) == 0x3
    assert int(dut.phy_dfi_wck_toggle.value) == 0x5
    assert int(dut.phy_dfi_wck_cs.value) == 0x1

    dut._log.info("v5.2 semantics verified on real wires")


@cocotb.test(timeout_time=2, timeout_unit="ms")
async def dfi_v6_0_wire_semantics_test(dut):
    await _bring_up(dut)
    b = DFIv6_0Behavior()
    mc = _BusView(dut, "mc_dfi")

    # ----- Alert rename: dfi_alert live, dfi_alert_n ignored -----
    assert b.crc(mc, None) is None
    dut.phy_dfi_alert_n.value = 0        # OLD wire — must be ignored
    await _edge(dut)
    assert b.crc(mc, None) is None, "v6.0 sampled the retired alert_n wire"
    dut.phy_dfi_alert_n.value = 1
    dut.phy_dfi_alert.value = 0          # renamed wire, DDR5 active low
    await _edge(dut)
    evt = b.crc(mc, None)
    assert evt is not None, "dfi_alert not sampled"
    dut.phy_dfi_alert.value = 1
    await _edge(dut)

    # ----- Error rename: phy_error live, error ignored -----
    dut.phy_dfi_error.value = 1          # OLD wire — must be ignored
    dut.phy_dfi_error_info.value = 0x7
    await _edge(dut)
    assert b.error_event(mc, None) is None, (
        "v6.0 sampled the retired dfi_error wire"
    )
    dut.phy_dfi_error.value = 0
    dut.phy_dfi_phy_error.value = 1
    dut.phy_dfi_phy_error_info.value = 0xC
    await _edge(dut)
    evt = b.error_event(mc, None)
    assert evt is not None and evt.code == 0xC
    dut.phy_dfi_phy_error.value = 0
    await _edge(dut)

    # ----- Disconnect removed in v6.0 -----
    dut.mc_dfi_disconnect_error.value = 1
    await _edge(dut)
    with pytest.raises(RemovedInThisVersionError):
        b.disconnect_request(mc, None)
    dut.mc_dfi_disconnect_error.value = 0

    # ----- Training stays removed -----
    with pytest.raises(RemovedInThisVersionError):
        b.training_step(mc, None)

    # ----- New v6.0 sleep wire passes through -----
    dut.mc_dfi_sleep.value = 1
    await _edge(dut)
    assert int(dut.phy_dfi_sleep.value) == 1
    dut.mc_dfi_sleep.value = 0

    # ----- PHY Managed inherited from v5.2 -----
    dut.phy_dfi_phymngd_req.value = 1
    dut.phy_dfi_phymngd_type.value = 1
    await _edge(dut)
    evt = b.phy_takeover(mc, None)
    assert evt is not None and evt.reason == "phy_managed"
    dut.phy_dfi_phymngd_req.value = 0

    dut._log.info("v6.0 semantics verified on real wires")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_dfi_v5_v6_wires(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    test_name = "test_dfi_v5_v6_wires"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi",
                         "dfi_shim_v5.sv"),
        ],
        toplevel="dfi_shim_v5",
        module="test_dfi_v5_v6_wires",
        sim_build=sim_build,
        extra_env={
            "COCOTB_LOG_LEVEL": "INFO",
            "COCOTB_RESULTS_FILE": os.path.join(
                log_dir, f"results_{test_name}.xml"),
        },
        extra_args=["-Wno-TIMESCALEMOD", "-Wno-UNUSED", "-Wno-DECLFILENAME"],
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
