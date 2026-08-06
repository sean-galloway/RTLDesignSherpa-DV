# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v2.1 baseline behavior — the per-version Strategy class root.

Spec-verified against the DFI v2.1.1 signal tables (Denali, 17 Jun
2010). What v2.1 actually defines — all implemented here, not raised:

  - **Update interface, bidirectional**: dfi_ctrlupd_req/ack (MC-
    initiated) AND dfi_phyupd_req/ack/type (PHY-initiated). The
    request/grant handshake did NOT arrive in v3.0; it is v2.1
    baseline (spec §3.4, Table 8).
  - **Frequency change** via dfi_init_start / dfi_init_complete
    (§3.5, §4.8): asserting init_start during normal operation is the
    request; the PHY accepts by de-asserting init_complete within
    tinit_start cycles, or the offer is withdrawn. There is no
    dedicated freq-change request wire in any DFI version.
  - **Training** (§3.6): read leveling, gate training (DDR3/LPDDR2)
    and write leveling (DDR3) via dfi_rdlvl_* / dfi_wrlvl_*.
  - **CA parity** (§3.5, v2.1.1 parity interface): dfi_parity_in /
    dfi_parity_error for DDR3 registered DIMMs.
  - **Low power control** (§3.7, 20 May 2009 addition): dfi_lp_req /
    dfi_lp_wakeup / dfi_lp_ack.

Not defined in v2.1 (methods raise NotSupportedInThisVersionError):
CRC (v3.0, via dfi_alert_n), the Error interface (v3.0), PHY Master
(v4.0), Disconnect (v4.0).

Subclasses override the methods that gained or shifted semantics in
their revision; the inheritance chain keeps "v4 is mostly v3"
expressible as method overrides rather than scattered conditionals.
"""

from __future__ import annotations

from typing import Any, Optional

from .events import (
    CAParityEvent,
    CRCEvent,
    DisconnectEvent,
    ErrorEvent,
    FreqChangeEvent,
    FreqChangeProtocol,
    LowPowerEvent,
    TakeoverEvent,
    TrainingEvent,
    TrainingPhase,
    UpdateEvent,
    UpdateState,
)
from .exceptions import NotSupportedInThisVersionError


def _bus_value(sig) -> int:
    """Return the integer value of a cocotb signal, 0 if unresolvable."""
    v = sig.value
    return v.integer if v.is_resolvable else 0


def _maybe(bus: Any, name: str):
    """Fetch an optionally-present bus signal (None if absent)."""
    return getattr(bus, name, None)


_V2_1 = "v2.1"


class DFIv2_1Behavior:
    """Strategy class for DFI v2.1 semantics.

    Pure-Python, stateless. All methods take ``(bus, state)`` where
    ``bus`` is the cocotb signal-handle bundle and ``state`` is a
    small per-channel object owned by the BFM. The behavior class
    never mutates the BFM's state; it returns event objects that the
    BFM routes to its queues.

    Sub-version note: DFIVersion collapses each major line onto one
    representative (V3_1 for v3.x, V5_2 for v5.x); behavior classes
    follow the enum.
    """

    version_label: str = _V2_1

    # ----- CRC area (introduced v3.0 via dfi_alert_n) -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """v2.1 predates DRAM write CRC (a DDR4 feature, v3.0+)."""
        raise NotSupportedInThisVersionError(
            "CRC error reporting (dfi_alert_n)", self.version_label, "v3.0"
        )

    # ----- Update interface (bidirectional since v2.1) -----

    def update_request(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """Sample dfi_ctrlupd_req (MC-initiated) and dfi_phyupd_req
        (PHY-initiated); both handshakes are v2.1 baseline.

        If both request wires assert in the same cycle, either side
        may acknowledge the other (spec §3.4); we report the MC
        request — the PHY-side event will surface once ctrlupd
        de-asserts if the MC request is the one that loses.

        PHY-initiated events carry dfi_phyupd_type (up to 4 duration
        modes, tphyupd_type0-3).
        """
        del state
        if _bus_value(bus.ctrlupd_req):
            return UpdateEvent(state=UpdateState.REQUESTED, initiator="mc")
        if _bus_value(bus.phyupd_req):
            type_sig = _maybe(bus, "phyupd_type")
            return UpdateEvent(
                state=UpdateState.REQUESTED,
                initiator="phy",
                update_type=_bus_value(type_sig) if type_sig is not None else 0,
            )
        return None

    def update_grant(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """Observe the acknowledge wires (dfi_ctrlupd_ack /
        dfi_phyupd_ack). Returns a GRANTED event while an ack is
        active; the BFM's set_ctrlupd_ack / set_phyupd_ack primitives
        do the driving.
        """
        del state
        if _bus_value(bus.ctrlupd_ack):
            return UpdateEvent(state=UpdateState.GRANTED, initiator="mc")
        if _bus_value(bus.phyupd_ack):
            return UpdateEvent(state=UpdateState.GRANTED, initiator="phy")
        return None

    # ----- PHY Master / Managed (introduced v4.0) -----

    def phy_takeover(self, bus: Any, state: Any) -> Optional[TakeoverEvent]:
        raise NotSupportedInThisVersionError(
            "PHY Master/Managed interface", self.version_label, "v4.0"
        )

    def phy_release(self, bus: Any, state: Any) -> None:
        raise NotSupportedInThisVersionError(
            "PHY Master/Managed interface", self.version_label, "v4.0"
        )

    # ----- Disconnect protocol (introduced v4.0) -----

    def disconnect_request(self, bus: Any, state: Any) -> Optional[DisconnectEvent]:
        raise NotSupportedInThisVersionError(
            "Disconnect Protocol", self.version_label, "v4.0"
        )

    def disconnect_release(self, bus: Any, state: Any) -> None:
        raise NotSupportedInThisVersionError(
            "Disconnect Protocol", self.version_label, "v4.0"
        )

    # ----- Frequency change (dfi_init_start handshake, v2.1 §4.8) -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """Detect a frequency-change request: dfi_init_start asserted
        during normal operation (i.e. after initialization completed).

        ``state`` may expose ``init_done`` (bool); when absent, any
        init_start assertion while dfi_init_complete is high is
        treated as a request — matching the spec's trigger condition
        ("once both init_complete and init_start have been asserted,
        init_start triggers frequency change").

        The Acknowledged/Not-Acknowledged outcome is a protocol *run*
        (PHY de-asserts init_complete within tinit_start, or ignores);
        this sampler reports the request with protocol=BASIC. v4.0+
        overrides enrich the event with the frequency indicator.
        """
        del state
        if _bus_value(bus.init_start) and _bus_value(bus.init_complete):
            ratio_sig = _maybe(bus, "freq_ratio")
            return FreqChangeEvent(
                protocol=FreqChangeProtocol.BASIC,
                freq_ratio=_bus_value(ratio_sig) if ratio_sig is not None else None,
            )
        return None

    # ----- Training (v2.1 §3.6: rdlvl / gate / wrlvl) -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """Sample the v2.1 training enables/requests.

        Emits one event per call, first match wins: read leveling
        (dfi_rdlvl_en or dfi_rdlvl_req), gate training
        (dfi_rdlvl_gate_en or dfi_rdlvl_gate_req), write leveling
        (dfi_wrlvl_en or dfi_wrlvl_req). The delay-register protocol
        (dfi_rdlvl_delay_X / load / edge) is a v2.1-only mechanism the
        BFM drives via primitives; it doesn't create distinct events.
        """
        del state
        for phase, en_name, req_name in (
            (TrainingPhase.READ_LEVELING, "rdlvl_en", "rdlvl_req"),
            (TrainingPhase.GATE_TRAINING, "rdlvl_gate_en", "rdlvl_gate_req"),
            (TrainingPhase.WRITE_LEVELING, "wrlvl_en", "wrlvl_req"),
        ):
            en = _maybe(bus, en_name)
            req = _maybe(bus, req_name)
            if (en is not None and _bus_value(en)) or (
                    req is not None and _bus_value(req)):
                return TrainingEvent(phase=phase, slice_idx=0)
        return None

    # ----- Error interface (introduced v3.0) -----

    def error_event(self, bus: Any, state: Any) -> Optional[ErrorEvent]:
        raise NotSupportedInThisVersionError(
            "Error interface", self.version_label, "v3.0"
        )

    # ----- CA parity (v2.1.1 parity interface, DDR3 DIMMs) -----

    def ca_parity_check(self, bus: Any, state: Any) -> Optional[CAParityEvent]:
        """Sample dfi_parity_error (PHY-driven, active high) — the
        v2.1.1 DDR3 registered-DIMM parity interface. The received
        parity bit mirrors dfi_parity_in for traceability.

        v3.0 renamed this wire dfi_alert_n (active LOW) and merged it
        with CRC reporting — see DFIv3_1Behavior.
        """
        del state
        err = _maybe(bus, "parity_error")
        if err is not None and _bus_value(err):
            parity_in = _maybe(bus, "parity_in")
            return CAParityEvent(
                parity_bit_expected=0,
                parity_bit_received=(
                    _bus_value(parity_in) if parity_in is not None else 0
                ),
            )
        return None

    # ----- Low power control (v2.1 §3.7) -----

    def low_power(self, bus: Any, state: Any) -> Optional[LowPowerEvent]:
        """Sample dfi_lp_req (MC-driven low-power opportunity). The
        wakeup-time encoding on dfi_lp_wakeup is valid with the
        request. v3.1 splits the request into ctrl/data wires.
        """
        del state
        req = _maybe(bus, "lp_req")
        if req is not None and _bus_value(req):
            wakeup = _maybe(bus, "lp_wakeup")
            return LowPowerEvent(
                channel="shared",
                wakeup=_bus_value(wakeup) if wakeup is not None else 0,
            )
        return None
