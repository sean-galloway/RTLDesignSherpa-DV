"""Unit tests for DFIv4_0Behavior.

v4.0 is the densest single-version semantic pivot in the v2.1-v5.x
range: PHY Master, Disconnect, Acknowledged/Not-Acknowledged
frequency-change split, training-optional + per-slice, and update
self-refresh-exit all land here.

After v4.0 there should be **no methods left raising**
NotSupportedInThisVersionError — every shift area in the catalog has
an implementation (stubbed or otherwise).
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv2_1Behavior,
    DFIv3_1Behavior,
    DFIv4_0Behavior,
    FreqChangeProtocol,
    NotSupportedInThisVersionError,
)

from .conftest import MockBus


@pytest.fixture
def b():
    return DFIv4_0Behavior()


_BUS = MockBus()    # all signals default to 0
_STATE = object()


# ---------------------------------------------------------------------
# v4.0-introduced areas: should no longer raise
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    ["phy_takeover", "phy_release",
     "disconnect_request", "disconnect_release",
     "freq_change",
     "training_step",
     "update_request",
     "crc"],
)
def test_v4_0_areas_no_longer_raise(b, method_name):
    method = getattr(b, method_name)
    result = method(_BUS, _STATE)
    # Stubs return None; no method raises by v4.0
    assert result is None


def test_no_method_raises_in_v4_0(b):
    """Verify the full surface: after v4.0 every catalog area returns
    a stub (None or no-op) rather than raising. This locks down the
    "all 8 shift areas reachable" property."""
    all_methods = [
        "crc", "update_request", "update_grant",
        "phy_takeover", "phy_release",
        "disconnect_request", "disconnect_release",
        "freq_change",
        "training_step",
        "error_event",
        "ca_parity_check",
    ]
    for name in all_methods:
        method = getattr(b, name)
        try:
            method(_BUS, _STATE)
        except NotSupportedInThisVersionError as e:
            pytest.fail(
                f"DFIv4_0Behavior.{name}() raised "
                f"NotSupportedInThisVersionError ({e.area}); expected stub"
            )


# ---------------------------------------------------------------------
# Inheritance chain
# ---------------------------------------------------------------------


def test_inherits_from_v3_1_and_v2_1(b):
    assert isinstance(b, DFIv3_1Behavior)
    assert isinstance(b, DFIv2_1Behavior)


def test_version_label_is_v4_0(b):
    assert b.version_label == "v4.0"


def test_no_state_on_instance(b):
    assert b.__dict__ == {}


# ---------------------------------------------------------------------
# Inherited v3.x behaviors still work
# ---------------------------------------------------------------------


def test_error_event_inherited_from_v3_x(b):
    """v4.0 didn't change the error interface — still v3.0 behavior."""
    assert b.error_event(_BUS, _STATE) is None


def test_ca_parity_inherited_from_v3_x(b):
    assert b.ca_parity_check(_BUS, _STATE) is None


# ---------------------------------------------------------------------
# freq_change() — v4.0 Ack/Not-Ack split
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "protocol_code, expected_proto",
    [
        (0, FreqChangeProtocol.BASIC),
        (1, FreqChangeProtocol.ACKNOWLEDGED),
        (2, FreqChangeProtocol.NOT_ACKNOWLEDGED),
    ],
)
def test_v4_0_freq_change_decodes_protocol(b, protocol_code, expected_proto):
    bus = MockBus(freq_change_req=1, freq_change_protocol=protocol_code)
    evt = b.freq_change(bus, None)
    assert evt is not None
    assert evt.protocol == expected_proto


def test_v4_0_freq_change_returns_none_when_no_request(b):
    bus = MockBus(freq_change_req=0, freq_change_protocol=1)
    assert b.freq_change(bus, None) is None


def test_v4_0_freq_change_unknown_code_falls_back_to_basic(b):
    bus = MockBus(freq_change_req=1, freq_change_protocol=3)
    evt = b.freq_change(bus, None)
    assert evt.protocol == FreqChangeProtocol.BASIC


# ---------------------------------------------------------------------
# phy_takeover / disconnect_request — v4.0 introductions
# ---------------------------------------------------------------------


def test_v4_0_phy_takeover_returns_none_when_quiet(b):
    bus = MockBus(phymstr_req=0)
    assert b.phy_takeover(bus, None) is None


def test_v4_0_phy_takeover_returns_event_when_req_high(b):
    bus = MockBus(phymstr_req=1)
    evt = b.phy_takeover(bus, None)
    assert evt is not None
    assert evt.reason == "phy_managed"


def test_v4_0_disconnect_returns_none_when_quiet(b):
    from CocoTBFramework.components.dfi.behaviors import DisconnectPhase
    del DisconnectPhase  # for import side-effect / re-import safety
    bus = MockBus(disconnect_req=0)
    assert b.disconnect_request(bus, None) is None


def test_v4_0_disconnect_returns_event_when_req_high(b):
    from CocoTBFramework.components.dfi.behaviors import DisconnectPhase
    bus = MockBus(disconnect_req=1)
    evt = b.disconnect_request(bus, None)
    assert evt is not None
    assert evt.phase == DisconnectPhase.REQUEST
