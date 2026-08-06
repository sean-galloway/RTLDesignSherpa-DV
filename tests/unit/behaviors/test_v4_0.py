"""Unit tests for DFIv4_0Behavior.

Spec-verified expectations (v4.0 book):
  - PHY Master interface samples dfi_phymstr_req and captures the
    type / state_sel / cs_state qualifiers
  - disconnect is dfi_disconnect_error (QOS vs error flag on a
    handshake break) — not a req/ack pair
  - frequency change is still init_start/init_complete; the event
    gains the dfi_frequency indicator
  - training adds write-DQ (wdqlvl) and DB training phases
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv4_0Behavior,
    DisconnectPhase,
    FreqChangeProtocol,
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
    return DFIv4_0Behavior()


# ---------------------------------------------------------------------
# PHY Master interface
# ---------------------------------------------------------------------


def test_phy_takeover_none_when_idle(b):
    assert b.phy_takeover(_quiet_bus(), _STATE) is None


def test_phy_takeover_captures_qualifiers(b):
    bus = _quiet_bus(phymstr_req=1, phymstr_type=2,
                     phymstr_state_sel=1, phymstr_cs_state=1)
    evt = b.phy_takeover(bus, _STATE)
    assert evt is not None
    assert evt.reason == "phy_master"
    assert evt.takeover_type == 2
    assert evt.state_sel == 1
    assert evt.cs_state == 1


def test_phy_release_is_noop_observer(b):
    assert b.phy_release(_quiet_bus(), _STATE) is None


# ---------------------------------------------------------------------
# Disconnect protocol
# ---------------------------------------------------------------------


def test_disconnect_none_when_flag_low(b):
    assert b.disconnect_request(_quiet_bus(), _STATE) is None


def test_disconnect_event_on_error_flag(b):
    evt = b.disconnect_request(_quiet_bus(disconnect_error=1), _STATE)
    assert evt is not None
    assert evt.phase == DisconnectPhase.REQUEST
    assert evt.error is True


# ---------------------------------------------------------------------
# Frequency change with indicator
# ---------------------------------------------------------------------


def test_freq_change_none_when_idle(b):
    assert b.freq_change(_quiet_bus(init_complete=1), _STATE) is None


def test_freq_change_captures_frequency_code(b):
    bus = _quiet_bus(init_start=1, init_complete=1,
                     frequency=7, freq_ratio=2)
    evt = b.freq_change(bus, _STATE)
    assert evt is not None
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.frequency_code == 7
    assert evt.freq_ratio == 2


# ---------------------------------------------------------------------
# Training — v4.0 additions
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "wire, phase",
    [
        ("wdqlvl_en", TrainingPhase.DQ_TRAINING),
        ("wdqlvl_req", TrainingPhase.DQ_TRAINING),
        ("db_train_en", TrainingPhase.DB_TRAINING),
    ],
)
def test_training_v4_0_phases(b, wire, phase):
    evt = b.training_step(_quiet_bus(**{wire: 1}), _STATE)
    assert evt is not None
    assert evt.phase == phase


def test_training_inherits_v3_phases(b):
    evt = b.training_step(_quiet_bus(calvl_en=1), _STATE)
    assert evt.phase == TrainingPhase.CA_TRAINING


# ---------------------------------------------------------------------
# Inherited areas
# ---------------------------------------------------------------------


def test_crc_via_alert_n_inherited(b):
    evt = b.crc(_quiet_bus(alert_n=0), _STATE)
    assert evt is not None


def test_version_label(b):
    assert b.version_label == "v4.0"


def test_stateless(b):
    assert b.__dict__ == {}
