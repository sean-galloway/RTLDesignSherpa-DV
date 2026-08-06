"""Unit tests for DFIv3_1Behavior (covers the v3.0 + v3.1 shifts).

Spec-verified expectations (v3.1 book):
  - dfi_alert_n (ACTIVE LOW) replaces v2.1's dfi_parity_error and
    carries both CRC and CA-parity errors → crc() samples it;
    ca_parity_check() returns None (no double-reporting)
  - error interface (dfi_error / dfi_error_info) is real
  - training adds CA training (dfi_calvl_*) and PHY-requested
    training (dfi_phylvl_req_cs_n, active low)
  - low power requests split into ctrl/data wires
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    CRCKind,
    DFIv3_1Behavior,
    ErrorKind,
    TrainingPhase,
)

from .conftest import MockBus

_STATE = object()
_IDLE_HIGH = {"phylvl_req_cs_n": 1, "alert_n": 1}


def _quiet_bus(**overrides):
    kwargs = dict(_IDLE_HIGH)
    kwargs.update(overrides)
    return MockBus(**kwargs)


@pytest.fixture
def b():
    return DFIv3_1Behavior()


# ---------------------------------------------------------------------
# CRC / alert_n
# ---------------------------------------------------------------------


def test_crc_none_while_alert_idles_high(b):
    assert b.crc(_quiet_bus(), _STATE) is None


def test_crc_event_when_alert_n_low(b):
    """dfi_alert_n is ACTIVE LOW — 0 means an error was reported."""
    evt = b.crc(_quiet_bus(alert_n=0), _STATE)
    assert evt is not None
    assert evt.kind == CRCKind.DRAM_CRC


def test_crc_unresolvable_alert_treated_as_idle(b):
    bus = _quiet_bus()
    bus.alert_n.value.is_resolvable = False
    bus.alert_n.value.integer = 0
    assert b.crc(bus, _STATE) is None


# ---------------------------------------------------------------------
# CA parity folded into alert_n from v3.0
# ---------------------------------------------------------------------


def test_ca_parity_always_none_in_v3_x(b):
    """Parity errors ride dfi_alert_n (as CRCEvent); the dedicated
    v2.1 wire is gone and ca_parity_check never double-reports."""
    assert b.ca_parity_check(_quiet_bus(parity_error=1), _STATE) is None
    assert b.ca_parity_check(_quiet_bus(alert_n=0), _STATE) is None


# ---------------------------------------------------------------------
# Error interface
# ---------------------------------------------------------------------


def test_error_event_none_when_idle(b):
    assert b.error_event(_quiet_bus(), _STATE) is None


def test_error_event_carries_info_code(b):
    evt = b.error_event(_quiet_bus(error=1, error_info=0x42), _STATE)
    assert evt is not None
    assert evt.kind == ErrorKind.OTHER
    assert evt.code == 0x42


# ---------------------------------------------------------------------
# Training — v2.1 handshakes + v3.x additions
# ---------------------------------------------------------------------


def test_training_none_when_idle(b):
    assert b.training_step(_quiet_bus(), _STATE) is None


def test_training_inherits_v2_1_phases(b):
    evt = b.training_step(_quiet_bus(rdlvl_en=1), _STATE)
    assert evt.phase == TrainingPhase.READ_LEVELING


def test_training_ca_training_via_calvl(b):
    evt = b.training_step(_quiet_bus(calvl_en=1), _STATE)
    assert evt.phase == TrainingPhase.CA_TRAINING
    evt = b.training_step(_quiet_bus(calvl_req=1), _STATE)
    assert evt.phase == TrainingPhase.CA_TRAINING


def test_training_phy_requested_active_low(b):
    """dfi_phylvl_req_cs_n is per-CS active low: a cleared bit is a
    request; all-ones is idle."""
    evt = b.training_step(_quiet_bus(phylvl_req_cs_n=0), _STATE)
    assert evt is not None
    assert evt.phase == TrainingPhase.PHY_REQUESTED


# ---------------------------------------------------------------------
# Low power — ctrl/data split (v3.1)
# ---------------------------------------------------------------------


def test_low_power_ctrl_request(b):
    evt = b.low_power(_quiet_bus(lp_ctrl_req=1, lp_wakeup=3), _STATE)
    assert evt is not None
    assert evt.channel == "ctrl"
    assert evt.wakeup == 3


def test_low_power_data_request(b):
    evt = b.low_power(_quiet_bus(lp_data_req=1), _STATE)
    assert evt.channel == "data"


def test_low_power_ctrl_wins_simultaneous(b):
    evt = b.low_power(_quiet_bus(lp_ctrl_req=1, lp_data_req=1), _STATE)
    assert evt.channel == "ctrl"


# ---------------------------------------------------------------------
# Inherited raises / inherited implementations
# ---------------------------------------------------------------------


def test_phy_master_still_raises(b):
    with pytest.raises(NotImplementedError):
        b.phy_takeover(_quiet_bus(), _STATE)


def test_disconnect_still_raises(b):
    with pytest.raises(NotImplementedError):
        b.disconnect_request(_quiet_bus(), _STATE)


def test_update_inherited_from_v2_1(b):
    evt = b.update_request(_quiet_bus(phyupd_req=1, phyupd_type=1), _STATE)
    assert evt.initiator == "phy"
    assert evt.update_type == 1


def test_version_label(b):
    assert b.version_label == "v3.1"


def test_stateless(b):
    assert b.__dict__ == {}
