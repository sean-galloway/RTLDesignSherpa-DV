"""Unit tests for DFIv3_1Behavior.

Verifies that v3.x-introduced areas (CRC, Update grant, Training,
Error, CA-parity, Frequency-indicator) override the v2.1 raises and
return None as stubs. Areas still post-v3.1 (PHY Master, Disconnect)
must still raise — inherited from the v2.1 base.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    CRCKind,
    DFIv2_1Behavior,
    DFIv3_1Behavior,
    ErrorKind,
    NotSupportedInThisVersionError,
    UpdateState,
)

from .conftest import MockBus


@pytest.fixture
def b():
    return DFIv3_1Behavior()


_BUS = MockBus()   # all signals default to 0
_STATE = object()


# ---------------------------------------------------------------------
# v3.x-introduced areas: override v2.1's raise with stub returning None
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    ["crc", "update_grant", "training_step", "error_event",
     "ca_parity_check", "freq_change", "update_request"],
)
def test_v3_x_areas_no_longer_raise(b, method_name):
    """Each v3.x-introduced area should return None (stub) instead
    of raising NotSupportedInThisVersionError."""
    method = getattr(b, method_name)
    result = method(_BUS, _STATE)
    assert result is None


# ---------------------------------------------------------------------
# Post-v3.1 areas: still raise (inherited from v2.1)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name, expected_intro",
    [
        ("phy_takeover",        "v4.0"),
        ("phy_release",         "v4.0"),
        ("disconnect_request",  "v4.0"),
        ("disconnect_release",  "v4.0"),
    ],
)
def test_post_v3_1_areas_still_raise(b, method_name, expected_intro):
    method = getattr(b, method_name)
    with pytest.raises(NotSupportedInThisVersionError) as exc_info:
        method(_BUS, _STATE)
    assert exc_info.value.introduced_in == expected_intro
    # version field reports v3.1, not v2.1 (subclass overrides version_label)
    assert exc_info.value.version == "v3.1"


# ---------------------------------------------------------------------
# Class metadata + inheritance
# ---------------------------------------------------------------------


def test_inherits_from_v2_1(b):
    assert isinstance(b, DFIv2_1Behavior)


def test_version_label_is_v3_1(b):
    assert b.version_label == "v3.1"


def test_no_state_on_instance(b):
    """Still stateless."""
    assert b.__dict__ == {}


# ---------------------------------------------------------------------
# Spot-check: error message embeds the right version
# ---------------------------------------------------------------------


def test_phy_takeover_error_message_includes_v3_1(b):
    """When DFIv3_1Behavior.phy_takeover raises, the message names v3.1
    as the *current* version (not v2.1) so users see what they actually
    have configured."""
    with pytest.raises(NotSupportedInThisVersionError) as exc_info:
        b.phy_takeover(_BUS, _STATE)
    assert "v3.1" in str(exc_info.value)
    assert "v4.0" in str(exc_info.value)  # introduced-in


# ---------------------------------------------------------------------
# error_event() — first real implementation (not a stub)
# ---------------------------------------------------------------------


def test_error_event_returns_none_when_error_signal_low(b):
    bus = MockBus(error=0, error_info=0)
    assert b.error_event(bus, None) is None


def test_error_event_returns_event_when_error_signal_asserted(b):
    bus = MockBus(error=1, error_info=0x42)
    evt = b.error_event(bus, None)
    assert evt is not None
    assert evt.kind == ErrorKind.OTHER
    assert evt.code == 0x42


def test_error_event_carries_info_bits_as_code(b):
    """error_info field maps directly to ErrorEvent.code in the MVP
    decoding (no spec-info-encoding lookup yet)."""
    bus = MockBus(error=1, error_info=0xff)
    evt = b.error_event(bus, None)
    assert evt.code == 0xff


def test_error_event_ignores_state_arg(b):
    """state is positional in the API but unused for error_event."""
    bus = MockBus(error=1, error_info=0x1)
    assert b.error_event(bus, "any state").code == 0x1
    assert b.error_event(bus, None).code == 0x1
    assert b.error_event(bus, 42).code == 0x1


# ---------------------------------------------------------------------
# crc() — implementation (not a stub)
# ---------------------------------------------------------------------


def test_crc_returns_none_when_alert_low(b):
    bus = MockBus(crc_alert=0)
    assert b.crc(bus, None) is None


def test_crc_returns_event_when_alert_high(b):
    bus = MockBus(crc_alert=1)
    evt = b.crc(bus, None)
    assert evt is not None
    assert evt.kind == CRCKind.DRAM_CRC


def test_crc_mvp_slice_idx_is_zero(b):
    """v3.0 MVP doesn't distinguish per-slice; v4.0 overrides for that."""
    bus = MockBus(crc_alert=1)
    evt = b.crc(bus, None)
    assert evt.slice_idx == 0


# ---------------------------------------------------------------------
# update_request() — bidirectional handshake (v3.0 introduction)
# ---------------------------------------------------------------------


def test_update_returns_none_when_quiet(b):
    bus = MockBus(ctrlupd_req=0, phyupd_req=0)
    assert b.update_request(bus, None) is None


def test_update_detects_mc_initiated(b):
    bus = MockBus(ctrlupd_req=1, phyupd_req=0)
    evt = b.update_request(bus, None)
    assert evt is not None
    assert evt.state == UpdateState.REQUESTED
    assert evt.initiator == "mc"


def test_update_detects_phy_initiated(b):
    bus = MockBus(ctrlupd_req=0, phyupd_req=1)
    evt = b.update_request(bus, None)
    assert evt is not None
    assert evt.state == UpdateState.REQUESTED
    assert evt.initiator == "phy"


def test_update_mc_takes_priority_when_both_asserted(b):
    """Per the spec, an active MC-initiated request wins over a
    simultaneous PHY-initiated one."""
    bus = MockBus(ctrlupd_req=1, phyupd_req=1)
    evt = b.update_request(bus, None)
    assert evt.initiator == "mc"
