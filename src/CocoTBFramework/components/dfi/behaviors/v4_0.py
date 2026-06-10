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
    FreqChangeEvent,
    TakeoverEvent,
    TrainingEvent,
    UpdateEvent,
)
from .v3_1 import DFIv3_1Behavior


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
        """v4.0 PHY-master mode — PHY can take bus ownership.

        Stub returns None. When implemented, a takeover detection
        constructs ``TakeoverEvent(reason="…")`` where reason names
        the spec-defined justification ("recalibration",
        "autonomous_refresh", etc.).
        """
        del bus, state
        return None

    def phy_release(self, bus: Any, state: Any) -> None:
        """v4.0 PHY-master mode release — PHY hands the bus back.

        Stub is a no-op until the BFM plumbs the wire-drive side.
        """
        del bus, state
        return None

    # ----- Disconnect Protocol: introduced v4.0 -----

    def disconnect_request(self, bus: Any, state: Any) -> Optional[DisconnectEvent]:
        """v4.0 Disconnect Protocol — coordinated PHY disengagement.

        Stub returns None. When implemented, a detection at the
        request phase constructs
        ``DisconnectEvent(phase=DisconnectPhase.REQUEST)``;
        the ack/release phases land via the same event type.
        """
        del bus, state
        return None

    def disconnect_release(self, bus: Any, state: Any) -> None:
        """v4.0 Disconnect Protocol — release side of the handshake.

        Stub is a no-op until the BFM plumbs the wire-drive side.
        """
        del bus, state
        return None

    # ----- Frequency change: v4.0 added Ack/Not-Ack split -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """v4.0 frequency change has Acknowledged and Not-Acknowledged
        sub-protocols (§4.11.1, §4.11.2 in v5.2 spec).

        Stub returns None. When implemented, the BFM will distinguish
        the two protocols by sampling the spec-defined handshake
        signals and constructing
        ``FreqChangeEvent(protocol=FreqChangeProtocol.ACKNOWLEDGED, …)``
        or ``FreqChangeProtocol.NOT_ACKNOWLEDGED``.

        v3.x's FreqChangeProtocol.BASIC is still reachable for
        backward-compat scenarios — the BFM decides per cycle which
        protocol is in flight.
        """
        del bus, state
        return None

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
