# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v4.0 behavior — the densest semantic-shift pivot.

v4.0 changes (per the v5.2 release notes' v4.0 entry):

  - **PHY Master Interface** introduced — PHY can take ownership of
    the DFI bus for autonomous operations. (Renamed to "PHY Managed
    Interface" in v5.2 but the contract is the same per the catalog.)
  - **Disconnect Protocol** introduced — coordinated handshake for
    PHY to disengage from the bus.
  - **Frequency change** split into Acknowledged and Not-Acknowledged
    protocols. Encoded via the ``protocol`` field on FreqChangeEvent.
  - **Training** became optional. Per-slice read leveling, DB training,
    and write DQ training added. Write leveling strobe semantics
    changed. Reflected via the per-slice ``slice_idx`` field already
    on TrainingEvent.
  - **Update interface** gained self-refresh-exit semantics — update
    can now interleave with self-refresh. Reflected via
    UpdateState.SELF_REFRESH_EXIT.
  - **CRC**: phycrc_mode parameter added — PHY can drive CRC for some
    configurations (phycrc_mode=1) alongside the v3.0 MC-driven path
    (phycrc_mode=0).

Inherits from DFIv3_1Behavior so areas not touched by v4.0 (Error
interface, CA parity, MC-initiated update request) keep their v3.x
behavior unchanged.
"""

from __future__ import annotations

from typing import Any, Optional

from .events import (
    CRCEvent,
    DisconnectEvent,
    DisconnectPhase,
    FreqChangeEvent,
    FreqChangeProtocol,
    TakeoverEvent,
    TrainingEvent,
    UpdateEvent,
)
from .v3_1 import DFIv3_1Behavior


_PROTOCOL_DECODE = {
    0: FreqChangeProtocol.BASIC,
    1: FreqChangeProtocol.ACKNOWLEDGED,
    2: FreqChangeProtocol.NOT_ACKNOWLEDGED,
}


def _bus_value(sig) -> int:
    v = sig.value
    return v.integer if v.is_resolvable else 0


class DFIv4_0Behavior(DFIv3_1Behavior):
    """Strategy class for DFI v4.0 semantics."""

    version_label: str = "v4.0"

    # CRC: v4.0 spec adds `phycrc_mode` branching atop v3.0 behavior.
    # Stub-only override removed — v3.1's crc() does real wire sampling
    # and is inherited. When phycrc_mode wiring lands, an override here
    # will read `state.phycrc_mode` and select the MC-driven (=0) or
    # PHY-driven (=1) sampling path.

    # ----- PHY Master Interface: introduced v4.0 -----

    def phy_takeover(self, bus: Any, state: Any) -> Optional[TakeoverEvent]:
        """v4.0 PHY-master mode — PHY takes bus ownership.

        Samples ``bus.phymstr_req``. Returns
        ``TakeoverEvent(reason="phy_managed")`` on assertion. The spec
        defines a reason field on the wire which we'd map to specific
        reason strings (recalibration / autonomous_refresh / training);
        the MVP uses a generic tag.
        """
        del state
        if _bus_value(bus.phymstr_req):
            return TakeoverEvent(reason="phy_managed")
        return None

    def phy_release(self, bus: Any, state: Any) -> None:
        """v4.0 PHY-master release — observed via phymstr_req deassertion.

        No-op observer; the deassertion edge is captured by absence of
        a takeover event on subsequent cycles. Method exists for API
        symmetry.
        """
        del bus, state
        return None

    # ----- Disconnect Protocol: introduced v4.0 -----

    def disconnect_request(self, bus: Any, state: Any) -> Optional[DisconnectEvent]:
        """v4.0 Disconnect Protocol — coordinated PHY disengagement.

        Samples ``bus.disconnect_req`` (active high). Returns
        ``DisconnectEvent(phase=DisconnectPhase.REQUEST)`` on assertion.
        Ack and release phases are tracked via the wire-drive side
        (``set_disconnect_req(0)``).
        """
        del state
        if _bus_value(bus.disconnect_req):
            return DisconnectEvent(phase=DisconnectPhase.REQUEST)
        return None

    def disconnect_release(self, bus: Any, state: Any) -> None:
        """v4.0 Disconnect release — paired with disconnect_request.

        No-op observer; release is implicit in disconnect_req deassertion.
        Method exists for API symmetry.
        """
        del bus, state
        return None

    # ----- Frequency change: v4.0 added Ack/Not-Ack split -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """v4.0 frequency change has Acknowledged and Not-Acknowledged
        sub-protocols (§4.11.1, §4.11.2 in v5.2 spec).

        Samples ``bus.freq_change_req`` and decodes
        ``bus.freq_change_protocol`` (2-bit field) into the right
        FreqChangeProtocol enum. BASIC remains reachable for
        backward-compat scenarios (protocol=0). Unknown protocol
        codes fall back to BASIC.
        """
        del state
        if not _bus_value(bus.freq_change_req):
            return None
        protocol = _PROTOCOL_DECODE.get(
            _bus_value(bus.freq_change_protocol), FreqChangeProtocol.BASIC,
        )
        return FreqChangeEvent(protocol=protocol)

    # Training: v4.0 spec adds optional flag + per-slice leveling +
    # DB training atop v3.0 behavior. Stub-only override removed —
    # v3.1's training_step() decodes the phase code correctly and is
    # inherited. When per-slice indexing wires land, an override here
    # will read slice_idx from a new bus signal.

    # Update: v4.0 spec adds self-refresh exit atop v3.0 behavior.
    # Stub-only override removed — v3.1's update_request() handles
    # the bidirectional handshake correctly and is inherited. When
    # self-refresh-exit wiring lands, an override here will emit
    # UpdateEvent(state=UpdateState.SELF_REFRESH_EXIT, …) when the
    # spec-defined signal pattern is observed.

    # Error interface and CA parity unchanged from v3.x — inherited.
