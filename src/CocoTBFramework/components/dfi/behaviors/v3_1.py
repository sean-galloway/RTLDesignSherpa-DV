# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v3.x behavior — collapses v3.0 and v3.1 conceptual shifts.

The catalog (``docs/internal/dfi-semantic-shifts.md``) distinguishes
v3.0 from v3.1, but ``DFIVersion`` enumerates only V3_1 as the
representative for the v3.x major. This class carries both:

v3.0 introductions (per v5.2 release notes):
  - CRC (write data, MC-driven path)
  - Update interface rewrite (full request/grant handshake)
  - Training interface (MC-driven)
  - Error interface
  - CA parity (DDR4-specific)
  - Frequency indicator (extends v2.1's basic freq-change)

v3.1 additions (per v5.2 release notes):
  - PHY-Requested Training Interface
  - Low Power Control Interface (split from Status)

Methods that override v2.1's raising stubs now return None or a
stubbed Event — full wire-level decoding lands when the BFM plumbs
the behavior into its sampling loop. PHY Master / Disconnect /
Acknowledged frequency change are still post-v3.1, so the
inherited v2.1 raises remain.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import DFIv2_1Behavior
from .events import (
    CAParityEvent,
    CRCEvent,
    ErrorEvent,
    ErrorKind,
    FreqChangeEvent,
    TrainingEvent,
    UpdateEvent,
)


def _bus_value(sig) -> int:
    """Return the integer value of a cocotb signal, 0 if unresolvable."""
    v = sig.value
    return v.integer if v.is_resolvable else 0


class DFIv3_1Behavior(DFIv2_1Behavior):
    """Strategy class for DFI v3.x semantics (covers v3.0 + v3.1)."""

    version_label: str = "v3.1"

    # ----- CRC area: introduced v3.0 -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """v3.0 CRC: MC-driven write-data CRC, PHY reports errors
        via the error interface.

        Stub returns None until wire-level CRC sampling is plumbed
        in. When implemented, a CRC mismatch should construct a
        ``CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=…, timestamp_ns=…)``.

        v4.0 overrides to add ``phycrc_mode=1`` (PHY-driven CRC) —
        see ``DFIv4_0Behavior.crc``.
        """
        del bus, state
        return None

    # ----- Update interface: rewritten v3.0 (request/grant handshake) -----

    def update_request(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """v3.0 update request supports both MC-initiated and
        PHY-initiated forms (bidirectional request/grant handshake).

        Stub returns None until wire sampling lands. When implemented,
        an active request should construct an
        ``UpdateEvent(state=UpdateState.REQUESTED, initiator=…)``.
        """
        del bus, state
        return None

    def update_grant(self, bus: Any, state: Any) -> None:
        """v3.0 added the grant path that v2.1 lacked.

        Stub is a no-op until the BFM plumbs the wire-drive side.
        """
        del bus, state
        return None

    # ----- Training: introduced v3.0; PHY-requested mode added v3.1 -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """v3.0 MC-driven training + v3.1 PHY-requested training.

        Stub returns None. When implemented, a training event should
        construct ``TrainingEvent(phase=TrainingPhase.READ_LEVELING …)``
        or similar. Use ``TrainingPhase.PHY_REQUESTED`` for the v3.1
        path where the PHY initiates training rather than the MC.

        Method shape will likely decompose into per-phase sub-methods
        when implementation lands — see the open question in the
        catalog about training being the highest-risk area for the
        single-method shape.
        """
        del bus, state
        return None

    # ----- Error interface: introduced v3.0 -----

    def error_event(self, bus: Any, state: Any) -> Optional[ErrorEvent]:
        """v3.0 error interface — PHY-driven first-class channel
        for parity / CRC / training failure reporting.

        Samples ``bus.error`` and ``bus.error_info`` each cycle. When
        ``error`` is asserted (non-zero), emit an ``ErrorEvent``
        carrying ``error_info`` as the code. The MVP doesn't decode the
        info field into specific ErrorKind values; that lands when the
        spec-defined info encoding is wired up.
        """
        del state
        if _bus_value(bus.error):
            return ErrorEvent(
                kind=ErrorKind.OTHER,
                code=_bus_value(bus.error_info),
            )
        return None

    # ----- CA parity: introduced v3.0 (DDR4 only) -----

    def ca_parity_check(self, bus: Any, state: Any) -> Optional[CAParityEvent]:
        """v3.0 CA-bus parity, gated on memory_type=DDR4 at the BFM.

        Stub returns None. When implemented, a parity mismatch
        constructs ``CAParityEvent(parity_bit_expected=…,
        parity_bit_received=…)``.
        """
        del bus, state
        return None

    # ----- Frequency change: extended v3.0 with frequency-indicator -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """v3.0 added the frequency-indicator signal — PHY can declare
        its current operating frequency back to the MC.

        Still using FreqChangeProtocol.BASIC for v3.x; the explicit
        Acknowledged/Not-Acknowledged split came in v4.0.

        Stub returns None until wire sampling lands.
        """
        del bus, state
        return None

    # PHY Master, Disconnect, Acknowledged freq-change: still raise
    # (inherited from v2.1). They land in DFIv4_0Behavior.
