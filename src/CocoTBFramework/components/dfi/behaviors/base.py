# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v2.1 baseline behavior — the per-version Strategy class root.

:class:`DFIv2_1Behavior` defines a method for every semantic-shift
area in the catalog (see ``docs/internal/dfi-semantic-shifts.md``).
Areas that don't exist in v2.1 — CRC, Update (request/grant), PHY
Master, Disconnect, Acknowledged frequency change, Training, Error
interface, CA parity — raise :class:`NotSupportedInThisVersionError`
so a v2.1 BFM exposed to a post-v2.1 wire pattern fails loudly
rather than silently returning a default.

The one area that *does* exist in v2.1 — the basic frequency-change
request — has a stub implementation returning a placeholder
:class:`FreqChangeEvent`. Real wire decoding lands when the BFM
plumbs the behavior into its sampling loop.

Subclasses (``DFIv3_1Behavior``, ``DFIv4_0Behavior``) override the
methods that gained or shifted semantics in their version. The
inheritance chain keeps "v4 is mostly v3" expressible as method
overrides rather than scattered conditionals.
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
    TakeoverEvent,
    TrainingEvent,
    UpdateEvent,
    UpdateState,
)
from .exceptions import NotSupportedInThisVersionError


def _bus_value(sig) -> int:
    """Return the integer value of a cocotb signal, 0 if unresolvable."""
    v = sig.value
    return v.integer if v.is_resolvable else 0


_V2_1 = "v2.1"


class DFIv2_1Behavior:
    """Strategy class for DFI v2.1 semantics.

    Pure-Python, stateless. All methods take ``(bus, state)`` where
    ``bus`` is the cocotb signal-handle bundle and ``state`` is a
    small per-channel dataclass owned by the BFM. The behavior class
    never mutates the BFM's state directly; it returns event objects
    that the BFM can route.

    Sub-version note: the catalog distinguishes v3.0 and v3.1 changes,
    but the DFIVersion enum collapses to V3_1 (representative of the
    v3.x major). Behavior subclassing follows the enum — so
    DFIv3_1Behavior carries both the v3.0-introduced shifts and the
    v3.1-introduced shifts.
    """

    # Identifier used in error messages
    version_label: str = _V2_1

    # ----- CRC area (introduced v3.0) -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """Sample CRC-related signals; return an event on mismatch."""
        raise NotSupportedInThisVersionError(
            "CRC handshake", self.version_label, "v3.0"
        )

    # ----- Update area (existed v2.1, rewritten v3.0, self-refresh v4.0) -----

    def update_request(self, bus: Any, state: Any) -> Optional[UpdateEvent]:
        """Sample for an MC-initiated update request.

        v2.1 had a simple single-cycle MC-initiated request. The
        request/grant handshake landed in v3.0 — see ``DFIv3_1Behavior``.
        """
        # v2.1 supports a basic MC-initiated request. Stub returns None
        # until BFM plumbs the actual wire sampling.
        return None

    def update_grant(self, bus: Any, state: Any) -> None:
        """Drive the grant response to an update request.

        v2.1 doesn't have a real grant — it was just an MC-initiated
        pulse with no PHY ack. The full request/grant handshake came
        in v3.0.
        """
        raise NotSupportedInThisVersionError(
            "update grant/handshake", self.version_label, "v3.0"
        )

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

    # ----- Frequency change (v2.1 basic; v4.0 added Ack/Not-Ack) -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """Sample for a frequency-change request.

        v2.1 supports only the basic protocol — single-cycle request,
        no explicit ack/nak variant. When ``bus.freq_change_req`` is
        asserted, emit ``FreqChangeEvent(protocol=BASIC)``.

        v4.0 overrides to inspect ``bus.freq_change_protocol`` and emit
        ACKNOWLEDGED or NOT_ACKNOWLEDGED variants.
        """
        del state
        if _bus_value(bus.freq_change_req):
            return FreqChangeEvent(protocol=FreqChangeProtocol.BASIC)
        return None

    # ----- Training (introduced v3.0) -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        raise NotSupportedInThisVersionError(
            "Training interface", self.version_label, "v3.0"
        )

    # ----- Error interface (introduced v3.0) -----

    def error_event(self, bus: Any, state: Any) -> Optional[ErrorEvent]:
        raise NotSupportedInThisVersionError(
            "Error interface", self.version_label, "v3.0"
        )

    # ----- CA parity (introduced v3.0 for DDR4+) -----

    def ca_parity_check(self, bus: Any, state: Any) -> Optional[CAParityEvent]:
        raise NotSupportedInThisVersionError(
            "CA parity signaling", self.version_label, "v3.0"
        )
