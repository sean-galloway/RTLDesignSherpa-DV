# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v4.0 behavior — the densest semantic-shift pivot.

Spec-verified against the v4.0 book (revision history + chapter 3).
v4.0 changes vs v3.1:

  - **PHY Master Interface** (§3.10): dfi_phymstr_req / ack /
    cs_state / state_sel / type — the PHY takes control of the
    DFI/DRAM buses with the DRAM left in a defined state.
  - **Disconnect Protocol** (§3.12): the MC may break an in-flight
    ctrlupd / phyupd / training / phymstr handshake;
    dfi_disconnect_error flags QOS (0) vs error (1) disconnect.
    Low-power and frequency-change handshakes are NOT disconnectable.
  - **Frequency indicator** (dfi_frequency, 5 bits): layered on the
    unchanged init_start/init_complete protocol; must be valid and
    stable while init_start is high.
  - **Training**: became optional per-operation (PHY Independent
    Mode); per-slice read leveling; write DQ training (dfi_wdqlvl_*);
    DB training for DDR4 LRDIMM (dfi_db_train_*); LPDDR4 CA VREF
    training; the ``*_cs_n`` wires renamed to ``*_cs``.
  - **Update interface**: a ctrlupd handshake is now required
    immediately before self-refresh exit (same wires).
  - dfi_data_byte_disable removed (replaced by the dfidata_bit_enable
    programmable parameter); dfi_cs_n renamed dfi_cs; DDR4 geardown
    (dfi_geardown_en) added.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import _active_slice, _bus_value, _maybe
from .events import (
    DisconnectEvent,
    DisconnectPhase,
    FreqChangeEvent,
    FreqChangeProtocol,
    GearDownEvent,
    TakeoverEvent,
    TrainingEvent,
    TrainingPhase,
)
from .v3_1 import DFIv3_1Behavior


class DFIv4_0Behavior(DFIv3_1Behavior):
    """Strategy class for DFI v4.0 semantics."""

    version_label: str = "v4.0"

    # Wire-name prefix for the PHY-takeover interface; v5.2 subclass
    # swaps this for "phymngd" (the 5.2 rename).
    _takeover_prefix: str = "phymstr"
    _takeover_reason: str = "phy_master"

    # ----- PHY Master Interface: introduced v4.0 -----

    def phy_takeover(self, bus: Any, state: Any) -> Optional[TakeoverEvent]:
        """Sample dfi_phymstr_req; on assertion, capture the request
        qualifiers (type = duration class tphymstr_type0-3, state_sel
        = IDLE vs self-refresh, cs_state = per-rank DRAM state).
        """
        del state
        req = _maybe(bus, f"{self._takeover_prefix}_req")
        if req is None or not _bus_value(req):
            return None

        def _q(suffix: str) -> int:
            sig = _maybe(bus, f"{self._takeover_prefix}_{suffix}")
            return _bus_value(sig) if sig is not None else 0

        return TakeoverEvent(
            reason=self._takeover_reason,
            takeover_type=_q("type"),
            state_sel=_q("state_sel"),
            cs_state=_q("cs_state"),
        )

    def phy_release(self, bus: Any, state: Any) -> None:
        """Release is observed via req deassertion on later samples;
        no dedicated wire. Method exists for API symmetry."""
        del bus, state
        return None

    # ----- Disconnect Protocol: introduced v4.0 -----

    def disconnect_request(self, bus: Any, state: Any) -> Optional[DisconnectEvent]:
        """A disconnect is the MC *breaking* an in-flight handshake —
        there is no request/ack wire pair. The one dedicated signal,
        dfi_disconnect_error, qualifies the break: 0 = QOS (PHY stays
        fully operational), 1 = error disconnect.

        This sampler reports dfi_disconnect_error assertion; detecting
        the broken handshake itself (req dropped while ack high) is
        the BFM state machine's job, which can pair its observation
        with this event's error flag.
        """
        del state
        err = _maybe(bus, "disconnect_error")
        if err is not None and _bus_value(err):
            return DisconnectEvent(phase=DisconnectPhase.REQUEST, error=True)
        return None

    def disconnect_release(self, bus: Any, state: Any) -> None:
        """No dedicated release wire; the disconnect completes when the
        broken handshake's wires return to idle within
        t*_disconnect(_error). Method exists for API symmetry."""
        del bus, state
        return None

    # ----- Frequency change: v4.0 adds the dfi_frequency indicator -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """Same init_start/init_complete protocol as v2.1; the v4.0
        event additionally captures dfi_frequency (5-bit indicator,
        valid while init_start is high) and the current freq_ratio.
        """
        del state
        if not (_bus_value(bus.init_start) and _bus_value(bus.init_complete)):
            return None
        freq_sig = _maybe(bus, "frequency")
        ratio_sig = _maybe(bus, "freq_ratio")
        return FreqChangeEvent(
            protocol=FreqChangeProtocol.BASIC,
            frequency_code=_bus_value(freq_sig) if freq_sig is not None else None,
            freq_ratio=_bus_value(ratio_sig) if ratio_sig is not None else None,
        )

    # ----- Training: v4.0 adds write-DQ, DB, and CA-VREF training -----

    def _per_slice_field(self, sig, slice_idx: int, width: int) -> Optional[int]:
        """Extract the ``width``-bit value for ``slice_idx`` from a
        per-slice bus. Falls back to the raw integer when the signal
        width is not introspectable (e.g. mock buses).
        """
        if sig is None:
            return None
        try:
            total_width = len(sig)
        except TypeError:
            total_width = width
        slice_count = total_width // width if width else 1
        if slice_count <= 1:
            return _bus_value(sig)
        if not 0 <= slice_idx < slice_count:
            return None
        val = _bus_value(sig)
        return (val >> (slice_idx * width)) & ((1 << width) - 1)

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """v3.x phases plus v4.0's write DQ training (dfi_wdqlvl_en /
        req), DDR4 LRDIMM DB training (dfi_db_train_en), and LPDDR4
        CA-VREF training (dfi_calvl_data/done/result/strobe).
        """
        evt = super().training_step(bus, state)
        if evt is not None:
            # Enrich LPDDR4 CA-VREF training with the v4.0 handshake
            # signals. calvl_en/calvl_req are per-slice; pick the
            # active slice the same way read leveling does.
            if evt.phase == TrainingPhase.CA_TRAINING:
                calvl_en = _maybe(bus, "calvl_en")
                calvl_req = _maybe(bus, "calvl_req")
                en_active = calvl_en is not None and _bus_value(calvl_en)
                slice_idx = _active_slice(
                    calvl_en if en_active else calvl_req)
                data = self._per_slice_field(
                    _maybe(bus, "calvl_data"), slice_idx, 7)
                strobe = self._per_slice_field(
                    _maybe(bus, "calvl_strobe"), slice_idx, 1)
                done_sig = _maybe(bus, "calvl_done")
                result_sig = _maybe(bus, "calvl_result")
                return TrainingEvent(
                    phase=TrainingPhase.CA_TRAINING,
                    slice_idx=slice_idx,
                    calvl_data=data,
                    calvl_done=bool(_bus_value(done_sig))
                    if done_sig is not None else None,
                    calvl_result=bool(_bus_value(result_sig))
                    if result_sig is not None else None,
                    calvl_strobe=bool(strobe) if strobe is not None else None,
                )
            return evt
        for phase, en_name, req_name in (
            (TrainingPhase.DQ_TRAINING, "wdqlvl_en", "wdqlvl_req"),
            (TrainingPhase.DB_TRAINING, "db_train_en", None),
        ):
            en = _maybe(bus, en_name)
            if en is not None and _bus_value(en):
                return TrainingEvent(phase=phase, slice_idx=0)
            if req_name is not None:
                req = _maybe(bus, req_name)
                if req is not None and _bus_value(req):
                    return TrainingEvent(phase=phase, slice_idx=0)
        return None

    # ----- Geardown mode: v4.0 dfi_geardown_en (DDR4) -----

    def geardown(self, bus: Any, state: Any) -> Optional[GearDownEvent]:
        """Sample dfi_geardown_en and report entry into geardown mode.

        v4.0 added this signal for DDR4; it is removed in v5.x (the
        spec superseded it with dfi_cs_geardown / 2N mode). The event
        reports the assertion; de-assertion is the idle/normal state.
        """
        del state
        sig = _maybe(bus, "geardown_en")
        if sig is not None and _bus_value(sig):
            return GearDownEvent(enabled=True)
        return None

    # CRC (alert_n), Error interface, CA parity, Low power, Update:
    # inherited from v3.x unchanged.
