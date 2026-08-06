"""Unit tests for DFIv2_1Behavior — the baseline behavior class.

Spec-verified expectations (DFI v2.1.1 signal tables):
  - areas that DON'T exist in v2.1 (CRC/alert_n, error interface,
    PHY master, disconnect) raise NotSupportedInThisVersionError with
    the right area / introduced-in metadata
  - areas that DO exist in v2.1 — and there are more than the old
    catalog assumed — sample real wires: bidirectional update
    (ctrlupd + phyupd), frequency change via init_start/init_complete,
    rdlvl/wrlvl training, DDR3-DIMM CA parity (dfi_parity_error), and
    low power (dfi_lp_req)
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv2_1Behavior,
    FreqChangeProtocol,
    NotSupportedInThisVersionError,
    TrainingPhase,
    UpdateState,
)

from .conftest import MockBus

# Signals that idle at 1 (active-low request wires) — used to build
# quiet buses so auto-zero defaults don't read as active requests.
_IDLE_HIGH = {"phylvl_req_cs_n": 1, "alert_n": 1}


@pytest.fixture
def b():
    return DFIv2_1Behavior()


_STATE = object()


def _quiet_bus(**overrides):
    kwargs = dict(_IDLE_HIGH)
    kwargs.update(overrides)
    return MockBus(**kwargs)


# ---------------------------------------------------------------------
# Post-v2.1 areas should raise
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name, expected_area, expected_intro",
    [
        ("crc",                "CRC error reporting (dfi_alert_n)",  "v3.0"),
        ("phy_takeover",       "PHY Master/Managed interface",       "v4.0"),
        ("phy_release",        "PHY Master/Managed interface",       "v4.0"),
        ("disconnect_request", "Disconnect Protocol",                "v4.0"),
        ("disconnect_release", "Disconnect Protocol",                "v4.0"),
        ("error_event",        "Error interface",                    "v3.0"),
    ],
)
def test_post_v2_1_method_raises(b, method_name, expected_area, expected_intro):
    method = getattr(b, method_name)
    with pytest.raises(NotSupportedInThisVersionError) as exc_info:
        method(_quiet_bus(), _STATE)
    assert exc_info.value.area == expected_area
    assert exc_info.value.version == "v2.1"
    assert exc_info.value.introduced_in == expected_intro


def test_exception_inherits_notimplementederror(b):
    """So generic try/except NotImplementedError handlers can catch it."""
    with pytest.raises(NotImplementedError):
        b.crc(_quiet_bus(), _STATE)


# ---------------------------------------------------------------------
# Update interface — bidirectional since v2.1 (NOT a v3.0 addition)
# ---------------------------------------------------------------------


def test_update_request_none_when_idle(b):
    assert b.update_request(_quiet_bus(), _STATE) is None


def test_update_request_mc_initiated(b):
    evt = b.update_request(_quiet_bus(ctrlupd_req=1), _STATE)
    assert evt is not None
    assert evt.state == UpdateState.REQUESTED
    assert evt.initiator == "mc"


def test_update_request_phy_initiated_carries_type(b):
    """v2.1 defines dfi_phyupd_req/ack/type — the PHY-initiated path
    is baseline, not a v3.0 rewrite."""
    evt = b.update_request(_quiet_bus(phyupd_req=1, phyupd_type=2), _STATE)
    assert evt is not None
    assert evt.initiator == "phy"
    assert evt.update_type == 2


def test_update_request_mc_wins_simultaneous(b):
    evt = b.update_request(_quiet_bus(ctrlupd_req=1, phyupd_req=1), _STATE)
    assert evt.initiator == "mc"


def test_update_grant_observes_acks(b):
    """v2.1 has real acks in both directions; update_grant no longer
    raises."""
    assert b.update_grant(_quiet_bus(), _STATE) is None
    evt = b.update_grant(_quiet_bus(ctrlupd_ack=1), _STATE)
    assert evt.state == UpdateState.GRANTED
    assert evt.initiator == "mc"
    evt = b.update_grant(_quiet_bus(phyupd_ack=1), _STATE)
    assert evt.initiator == "phy"


# ---------------------------------------------------------------------
# Frequency change — dfi_init_start / dfi_init_complete handshake
# ---------------------------------------------------------------------


def test_freq_change_none_when_idle(b):
    assert b.freq_change(_quiet_bus(init_complete=1), _STATE) is None


def test_freq_change_requires_init_complete(b):
    """init_start during initialization (init_complete low) is setup,
    not a frequency-change request."""
    assert b.freq_change(_quiet_bus(init_start=1, init_complete=0), _STATE) is None


def test_freq_change_emits_on_init_start_during_operation(b):
    bus = _quiet_bus(init_start=1, init_complete=1, freq_ratio=1)
    evt = b.freq_change(bus, _STATE)
    assert evt is not None
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.freq_ratio == 1


# ---------------------------------------------------------------------
# Training — exists in v2.1 (rdlvl / gate / wrlvl)
# ---------------------------------------------------------------------


def test_training_none_when_idle(b):
    assert b.training_step(_quiet_bus(), _STATE) is None


@pytest.mark.parametrize(
    "wire, phase",
    [
        ("rdlvl_en", TrainingPhase.READ_LEVELING),
        ("rdlvl_req", TrainingPhase.READ_LEVELING),
        ("rdlvl_gate_en", TrainingPhase.GATE_TRAINING),
        ("rdlvl_gate_req", TrainingPhase.GATE_TRAINING),
        ("wrlvl_en", TrainingPhase.WRITE_LEVELING),
        ("wrlvl_req", TrainingPhase.WRITE_LEVELING),
    ],
)
def test_training_v2_1_wires(b, wire, phase):
    evt = b.training_step(_quiet_bus(**{wire: 1}), _STATE)
    assert evt is not None
    assert evt.phase == phase


# ---------------------------------------------------------------------
# CA parity — v2.1.1 DDR3-DIMM parity interface (dfi_parity_error)
# ---------------------------------------------------------------------


def test_ca_parity_none_when_idle(b):
    assert b.ca_parity_check(_quiet_bus(), _STATE) is None


def test_ca_parity_event_on_parity_error(b):
    evt = b.ca_parity_check(_quiet_bus(parity_error=1, parity_in=1), _STATE)
    assert evt is not None
    assert evt.parity_bit_received == 1


# ---------------------------------------------------------------------
# Low power — v2.1 §3.7 (dfi_lp_req / lp_wakeup)
# ---------------------------------------------------------------------


def test_low_power_none_when_idle(b):
    assert b.low_power(_quiet_bus(), _STATE) is None


def test_low_power_shared_request(b):
    evt = b.low_power(_quiet_bus(lp_req=1, lp_wakeup=5), _STATE)
    assert evt is not None
    assert evt.channel == "shared"
    assert evt.wakeup == 5


# ---------------------------------------------------------------------
# Class metadata
# ---------------------------------------------------------------------


def test_version_label_is_v2_1(b):
    assert b.version_label == "v2.1"


def test_no_state_on_instance(b):
    """Behavior classes are stateless — instance dict should be empty."""
    assert b.__dict__ == {}
