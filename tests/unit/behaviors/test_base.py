"""Unit tests for DFIv2_1Behavior — the baseline behavior class.

Verifies that:
  - methods for post-v2.1 areas raise NotSupportedInThisVersionError
    with the right area / introduced-in metadata
  - methods for areas that exist in v2.1 (update_request, freq_change)
    return None as a stub (not raise)
  - the exception carries machine-readable fields for downstream
    routing
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv2_1Behavior,
    FreqChangeProtocol,
    NotSupportedInThisVersionError,
)

from .conftest import MockBus


@pytest.fixture
def b():
    return DFIv2_1Behavior()


# MockBus auto-defaults missing signals to 0, so freq_change reads 0 and returns None.
_BUS = MockBus()
_STATE = object()


# ---------------------------------------------------------------------
# Post-v2.1 areas should raise
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name, expected_area, expected_intro",
    [
        ("crc",                  "CRC handshake",               "v3.0"),
        ("update_grant",         "update grant/handshake",      "v3.0"),
        ("phy_takeover",         "PHY Master/Managed interface","v4.0"),
        ("phy_release",          "PHY Master/Managed interface","v4.0"),
        ("disconnect_request",   "Disconnect Protocol",         "v4.0"),
        ("disconnect_release",   "Disconnect Protocol",         "v4.0"),
        ("training_step",        "Training interface",          "v3.0"),
        ("error_event",          "Error interface",             "v3.0"),
        ("ca_parity_check",      "CA parity signaling",         "v3.0"),
    ],
)
def test_post_v2_1_method_raises(b, method_name, expected_area, expected_intro):
    method = getattr(b, method_name)
    with pytest.raises(NotSupportedInThisVersionError) as exc_info:
        method(_BUS, _STATE)
    assert exc_info.value.area == expected_area
    assert exc_info.value.version == "v2.1"
    assert exc_info.value.introduced_in == expected_intro


def test_exception_inherits_notimplementederror(b):
    """So generic try/except NotImplementedError handlers can catch it."""
    with pytest.raises(NotImplementedError):
        b.crc(_BUS, _STATE)


# ---------------------------------------------------------------------
# v2.1 areas should return None as a stub
# ---------------------------------------------------------------------


def test_update_request_returns_none_in_v2_1(b):
    """v2.1 has a basic MC-initiated update request — stub returns None
    until wire sampling is plumbed in."""
    assert b.update_request(_BUS, _STATE) is None


def test_freq_change_returns_none_when_no_request(b):
    """v2.1 supports basic frequency change. With request=0, returns None."""
    assert b.freq_change(_BUS, _STATE) is None


def test_freq_change_v2_1_emits_basic_protocol(b):
    bus = MockBus(freq_change_req=1)
    evt = b.freq_change(bus, _STATE)
    assert evt is not None
    assert evt.protocol == FreqChangeProtocol.BASIC


# ---------------------------------------------------------------------
# Class metadata
# ---------------------------------------------------------------------


def test_version_label_is_v2_1(b):
    assert b.version_label == "v2.1"


def test_no_state_on_instance(b):
    """Behavior classes are stateless — instance dict should be empty."""
    assert b.__dict__ == {}
