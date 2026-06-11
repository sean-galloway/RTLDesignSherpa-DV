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

    # ----- CRC: phycrc_mode parameter added (v4.0) -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """v4.0 extends v3.0 CRC with phycrc_mode branching.

        Stub returns None. When implemented, the BFM will check the
        ``phycrc_mode`` configuration parameter on ``state`` and
        either:
          - sample the MC-driven CRC path (phycrc_mode=0; v3.0 behavior)
          - sample the PHY-driven CRC path (phycrc_mode=1; v4.0 addition)
        """
        del bus, state
        return None

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

    # ----- Training: optional flag + per-slice leveling (v4.0) -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """v4.0 made training optional and added per-slice operations.

        Stub returns None. When implemented:
          - The ``slice_idx`` field on TrainingEvent carries the
            v4.0+ per-slice index (ignored for v3.x callers).
          - TrainingPhase.DB_TRAINING covers the LPDDR4 DB-training
            mode v4.0 introduced.
          - "Training optional" surfaces as the BFM having an
            ``enable_training`` flag on its config; this method
            returns None when training is disabled.

        Per the catalog's open question on training: if this single
        method shape doesn't fit the read/write/DQ/CA leveling state
        machines, decompose into per-phase methods in a follow-up.
        """
        del bus, state
        return None

    # ----- Update: self-refresh exit (v4.0) -----

    def update_request(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """v4.0 update can interleave with self-refresh exit.

        Stub returns None. When implemented, an exit-from-self-refresh
        update path constructs
        ``UpdateEvent(state=UpdateState.SELF_REFRESH_EXIT, initiator=…)``.
        Normal v3.x update request paths (UpdateState.REQUESTED) still
        reachable.
        """
        del bus, state
        return None

    # Error interface and CA parity unchanged from v3.x — inherited.
