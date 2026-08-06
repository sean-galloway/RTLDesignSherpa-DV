"""Unit tests for DFIv6_0Behavior.

Spec-verified expectations (v6.0 book, May 2026):
  - dfi_alert (rename of alert_n) drives crc(); dfi_phy_error /
    dfi_phy_error_info (renames of error / error_info) drive
    error_event()
  - the disconnect protocol is REMOVED → raises
  - training stays removed (inherited from v5.x)
  - PHY Managed wires (phymngd) inherited from v5.2
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv6_0Behavior,
    RemovedInThisVersionError,
)

from .conftest import MockBus

_STATE = object()
_IDLE_HIGH = {"phylvl_req_cs_n": 1, "alert_n": 1, "alert": 1}


def _quiet_bus(**overrides):
    kwargs = dict(_IDLE_HIGH)
    kwargs.update(overrides)
    return MockBus(**kwargs)


@pytest.fixture
def b():
    return DFIv6_0Behavior()


# ---------------------------------------------------------------------
# Renamed error/alert wires
# ---------------------------------------------------------------------


def test_crc_samples_renamed_alert(b):
    assert b.crc(_quiet_bus(), _STATE) is None
    evt = b.crc(_quiet_bus(alert=0), _STATE)
    assert evt is not None


def test_crc_ignores_old_alert_n_wire(b):
    assert b.crc(_quiet_bus(alert_n=0), _STATE) is None


def test_error_event_samples_phy_error(b):
    evt = b.error_event(_quiet_bus(phy_error=1, phy_error_info=0xA), _STATE)
    assert evt is not None
    assert evt.code == 0xA


def test_error_event_ignores_old_error_wire(b):
    assert b.error_event(_quiet_bus(error=1, error_info=0xA), _STATE) is None


# ---------------------------------------------------------------------
# Removed areas
# ---------------------------------------------------------------------


def test_disconnect_removed_in_v6_0(b):
    with pytest.raises(RemovedInThisVersionError) as exc_info:
        b.disconnect_request(_quiet_bus(disconnect_error=1), _STATE)
    assert exc_info.value.removed_in == "v6.0"


def test_training_stays_removed(b):
    with pytest.raises(RemovedInThisVersionError):
        b.training_step(_quiet_bus(), _STATE)


# ---------------------------------------------------------------------
# Inherited areas
# ---------------------------------------------------------------------


def test_phymngd_takeover_inherited(b):
    evt = b.phy_takeover(_quiet_bus(phymngd_req=1, phymngd_type=1), _STATE)
    assert evt is not None
    assert evt.reason == "phy_managed"


def test_freq_change_inherited_with_split_ratios(b):
    bus = _quiet_bus(init_start=1, init_complete=1, data_freq_ratio=2)
    evt = b.freq_change(bus, _STATE)
    assert evt is not None
    assert evt.data_freq_ratio == 2


def test_version_label(b):
    assert b.version_label == "v6.0"


def test_stateless(b):
    assert b.__dict__ == {}
