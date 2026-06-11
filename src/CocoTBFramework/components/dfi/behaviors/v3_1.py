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
    CRCKind,
    ErrorEvent,
    ErrorKind,
    FreqChangeEvent,
    TrainingEvent,
    TrainingPhase,
    UpdateEvent,
    UpdateState,
)


# Phase-code → TrainingPhase enum. Encoded on the wire so the spec-
# defined phase distinction lives in event data, not in separate
# behavior methods (validated by the LiteDRAM survey — training is
# parallel hardware circuits under software sequencing, not a
# sequential state machine).
_PHASE_DECODE = {
    0: TrainingPhase.READ_LEVELING,
    1: TrainingPhase.WRITE_LEVELING,
    2: TrainingPhase.DQ_TRAINING,
    3: TrainingPhase.CA_TRAINING,
    4: TrainingPhase.DB_TRAINING,
}


def _bus_value(sig) -> int:
    """Return the integer value of a cocotb signal, 0 if unresolvable."""
    v = sig.value
    return v.integer if v.is_resolvable else 0


class DFIv3_1Behavior(DFIv2_1Behavior):
    """Strategy class for DFI v3.x semantics (covers v3.0 + v3.1)."""

    version_label: str = "v3.1"

    # ----- CRC area: introduced v3.0 -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """v3.0 CRC: MC-driven write-data CRC, PHY reports errors via
        the dedicated ``dfi_crc_alert`` signal (active high, mirrors
        DDR4's ALERT_n after PHY-side inversion).

        Samples ``bus.crc_alert`` each cycle. When asserted, emit a
        ``CRCEvent(kind=CRCKind.DRAM_CRC)`` — the v3.0 MVP doesn't
        distinguish per-slice; ``slice_idx`` stays at 0.

        v4.0 overrides to add ``phycrc_mode=1`` (PHY-driven CRC) and
        per-slice indexing — see ``DFIv4_0Behavior.crc``.
        """
        del state
        if _bus_value(bus.crc_alert):
            return CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=0)
        return None

    # ----- Update interface: rewritten v3.0 (request/grant handshake) -----

    def update_request(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """v3.0 update interface supports both MC- and PHY-initiated
        requests (bidirectional handshake).

        Samples ``bus.ctrlupd_req`` (MC→PHY) and ``bus.phyupd_req``
        (PHY→MC). When either is asserted, emit an UpdateEvent with the
        ``initiator`` field set accordingly. If both are asserted in the
        same cycle, MC-initiated wins (the spec gives priority to
        active MC requests).
        """
        del state
        if _bus_value(bus.ctrlupd_req):
            return UpdateEvent(state=UpdateState.REQUESTED, initiator="mc")
        if _bus_value(bus.phyupd_req):
            return UpdateEvent(state=UpdateState.REQUESTED, initiator="phy")
        return None

    def update_grant(self, bus: Any, state: Any) -> None:
        """v3.0 added the grant path that v2.1 lacked.

        Currently a no-op observer — the actual grant signals are
        driven by the BFM's set_ctrlupd_ack/set_phyupd_ack primitives,
        not by this behavior method. Method exists for API symmetry.
        """
        del bus, state
        return None

    # ----- Training: introduced v3.0; PHY-requested mode added v3.1 -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        """v3.0 training interface. Single method covers all phases
        (read/write/DQ/CA/DB leveling) — the phase distinction is
        carried in the event, not a separate method per phase.

        Architecturally validated by the LiteDRAM survey
        (docs/internal/dfi-semantic-shifts.md, section 6 open
        question): training circuits run in parallel hardware under
        software sequencing; phase is data, not control flow. One
        method, pattern-match the phase code in the event.

        Samples ``bus.training_active`` and ``bus.training_phase``.
        Returns a TrainingEvent with the decoded phase when active;
        unknown phase codes fall back to READ_LEVELING (the v3.0
        baseline phase) rather than raising — forward-compat with
        v4+ phase encodings.

        slice_idx is 0 for the v3.0 MVP; v4.0 per-slice indexing
        would override this method to carry the slice number.
        """
        del state
        if not _bus_value(bus.training_active):
            return None
        phase = _PHASE_DECODE.get(
            _bus_value(bus.training_phase), TrainingPhase.READ_LEVELING,
        )
        return TrainingEvent(phase=phase, slice_idx=0)

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
