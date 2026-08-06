# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v3.x behavior — collapses v3.0 and v3.1 shifts.

Spec-verified against the v3.1 book (revision history + chapter 3).

v3.0 introduced (vs v2.1.1):
  - DDR4 support: dfi_act_n / dfi_bg / dfi_cid command extensions,
    write CRC, DBI (dfi_rddata_dbi_n), CA parity timing
  - **dfi_alert_n** (active LOW) replacing v2.1's dfi_parity_error —
    now carrying BOTH write-CRC and CA-parity errors
  - the **Error interface** (dfi_error / dfi_error_info)
  - the training redesign: v2.1's delay-register protocol
    (mode/load/delay/edge wires) dropped in favor of en/req/resp
    handshakes; per-CS training targets (dfi_phy_*_cs_n); data-path
    chip selects (dfi_rddata_cs_n / dfi_wrdata_cs_n)
  - per-data-slice independent dfi_rddata_valid timing

v3.1 added (vs v3.0):
  - LPDDR3 support incl. **CA training** (dfi_calvl_*)
  - Low Power split: dfi_lp_req → dfi_lp_ctrl_req + dfi_lp_data_req
  - **PHY-requested training** (dfi_phylvl_req_cs_n /
    dfi_phylvl_ack_cs_n)

The update interface is NOT a v3.0 rewrite — both directions exist in
v2.1 (the base class implements them); v3.0 only refined idle-bus
definitions around the handshakes.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import DFIv2_1Behavior, _bus_value, _maybe
from .events import (
    CAParityEvent,
    CRCEvent,
    CRCKind,
    ErrorEvent,
    ErrorKind,
    LowPowerEvent,
    TrainingEvent,
    TrainingPhase,
)


class DFIv3_1Behavior(DFIv2_1Behavior):
    """Strategy class for DFI v3.x semantics (covers v3.0 + v3.1)."""

    version_label: str = "v3.1"

    # ----- CRC / alert: dfi_alert_n introduced v3.0 -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """Sample dfi_alert_n (ACTIVE LOW — mirrors DDR4's ALERT_n).

        DDR4 reports write-CRC and CA-parity errors on the same pin;
        they are indistinguishable at the DFI boundary, so events
        default to kind=DRAM_CRC. Callers with DRAM-mode-register
        knowledge can reinterpret.

        The wire idles high; an unresolvable (X/Z) sample is treated
        as idle, not as an error.
        """
        del state
        alert = _maybe(bus, "alert_n")
        if alert is None:
            return None
        v = alert.value
        if v.is_resolvable and v.integer == 0:
            return CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=0)
        return None

    # ----- Error interface: introduced v3.0 -----

    def error_event(self, bus: Any, state: Any) -> Optional[ErrorEvent]:
        """Sample dfi_error / dfi_error_info (v3.0 Error interface,
        §3.8). When dfi_error is asserted, dfi_error_info carries the
        implementation-defined error code.
        """
        del state
        if _bus_value(bus.error):
            return ErrorEvent(
                kind=ErrorKind.OTHER,
                code=_bus_value(bus.error_info),
            )
        return None

    # ----- CA parity: folded into dfi_alert_n from v3.0 -----

    def ca_parity_check(self, bus: Any, state: Any) -> Optional[CAParityEvent]:
        """v3.0 removed the dedicated dfi_parity_error wire; CA-parity
        errors now arrive on dfi_alert_n together with CRC errors and
        surface as CRCEvent via :meth:`crc`. Always returns None so
        the two samplers never double-report one alert assertion.
        """
        del bus, state
        return None

    # ----- Training: v3.0 redesign + v3.1 additions -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """v3.x training: the base read/gate/write-leveling handshakes
        (redesigned wires, same names for en/req) plus v3.1's CA
        training (dfi_calvl_en / dfi_calvl_req) and PHY-requested
        training (dfi_phylvl_req_cs_n, active low).
        """
        evt = super().training_step(bus, state)
        if evt is not None:
            return evt
        calvl_en = _maybe(bus, "calvl_en")
        calvl_req = _maybe(bus, "calvl_req")
        if (calvl_en is not None and _bus_value(calvl_en)) or (
                calvl_req is not None and _bus_value(calvl_req)):
            return TrainingEvent(phase=TrainingPhase.CA_TRAINING, slice_idx=0)
        phylvl_req = _maybe(bus, "phylvl_req_cs_n")
        if phylvl_req is not None:
            v = phylvl_req.value
            # Active low, per-CS: any 0 bit is an active request; idle
            # is all-ones. Signal width isn't always introspectable
            # (mock buses), so compare against the all-ones value of
            # the sampled integer's own width — a request is any
            # resolvable value with at least one cleared bit.
            try:
                width = len(phylvl_req)
            except TypeError:
                width = 1
            if v.is_resolvable and v.integer != (1 << width) - 1:
                return TrainingEvent(
                    phase=TrainingPhase.PHY_REQUESTED, slice_idx=0,
                )
        return None

    # ----- Low power: v3.1 ctrl/data request split -----

    def low_power(self, bus: Any, state: Any) -> Optional[LowPowerEvent]:
        """Sample dfi_lp_ctrl_req / dfi_lp_data_req (v3.1 split of
        v2.1's dfi_lp_req). Control-interface request wins the report
        if both assert in one cycle; the shared dfi_lp_wakeup encoding
        (still unified until v5.1) rides along.
        """
        del state
        wakeup_sig = _maybe(bus, "lp_wakeup")
        wakeup = _bus_value(wakeup_sig) if wakeup_sig is not None else 0
        ctrl = _maybe(bus, "lp_ctrl_req")
        if ctrl is not None and _bus_value(ctrl):
            return LowPowerEvent(channel="ctrl", wakeup=wakeup)
        data = _maybe(bus, "lp_data_req")
        if data is not None and _bus_value(data):
            return LowPowerEvent(channel="data", wakeup=wakeup)
        return None

    # Update interface: inherited from v2.1 unchanged (bidirectional
    # handshake is v2.1 baseline; v3.0 only tightened idle-bus rules).
    # Frequency change: inherited (init_start/init_complete protocol
    # is unchanged in v3.x; no indicator wire yet).
    # PHY Master / Disconnect: still post-v3.x — inherited raises.
