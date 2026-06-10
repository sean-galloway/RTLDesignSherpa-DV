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
