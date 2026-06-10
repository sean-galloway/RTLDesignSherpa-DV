"""Unit tests for DFIv3_1Behavior.

Verifies that v3.x-introduced areas (CRC, Update grant, Training,
Error, CA-parity, Frequency-indicator) override the v2.1 raises and
return None as stubs. Areas still post-v3.1 (PHY Master, Disconnect)
must still raise — inherited from the v2.1 base.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv2_1Behavior,
    DFIv3_1Behavior,
    NotSupportedInThisVersionError,
)


@pytest.fixture
def b():
    return DFIv3_1Behavior()


_BUS = object()
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
