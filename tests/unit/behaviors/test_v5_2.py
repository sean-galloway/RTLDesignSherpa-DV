"""Unit tests for DFIv5_2Behavior (the v5.x line).

Spec-verified expectations (v5.2 book):
  - the DFI training interface is REMOVED → training_step raises
    RemovedInThisVersionError
  - PHY takeover samples the RENAMED dfi_phymngd_* wires
  - frequency change captures the v5.2 cmd/data ratio split + FSP
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    DFIv5_2Behavior,
    FreqChangeProtocol,
    NotSupportedInThisVersionError,
    RemovedInThisVersionError,
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
    return DFIv5_2Behavior()


# ---------------------------------------------------------------------
# Training interface removed in v5.x
# ---------------------------------------------------------------------


def test_training_raises_removed(b):
    with pytest.raises(RemovedInThisVersionError) as exc_info:
        b.training_step(_quiet_bus(rdlvl_en=1), _STATE)
    assert exc_info.value.removed_in == "v5.0"
    assert exc_info.value.version == "v5.2"


def test_removed_error_is_not_supported_subclass(b):
    """Generic handlers catching NotSupportedInThisVersionError (or
    NotImplementedError) still work for removed areas."""
    with pytest.raises(NotSupportedInThisVersionError):
        b.training_step(_quiet_bus(), _STATE)


# ---------------------------------------------------------------------
# PHY Managed — renamed wires
# ---------------------------------------------------------------------


def test_takeover_samples_phymngd_wires(b):
    bus = _quiet_bus(phymngd_req=1, phymngd_type=3, phymngd_state_sel=1)
    evt = b.phy_takeover(bus, _STATE)
    assert evt is not None
    assert evt.reason == "phy_managed"
    assert evt.takeover_type == 3
    assert evt.state_sel == 1


def test_takeover_ignores_old_phymstr_wires(b):
    """A v5.2 BFM must NOT trigger on the pre-rename wire names."""
    assert b.phy_takeover(_quiet_bus(phymstr_req=1), _STATE) is None


# ---------------------------------------------------------------------
# Frequency change — split ratios + FSP
# ---------------------------------------------------------------------


def test_freq_change_captures_split_ratios(b):
    bus = _quiet_bus(init_start=1, init_complete=1, frequency=9,
                     cmd_freq_ratio=0, data_freq_ratio=3, freq_fsp=1)
    evt = b.freq_change(bus, _STATE)
    assert evt is not None
    assert evt.protocol == FreqChangeProtocol.BASIC
    assert evt.frequency_code == 9
    assert evt.cmd_freq_ratio == 0
    assert evt.data_freq_ratio == 3   # 'b11 = 1:8 (new in v5.2)
    assert evt.freq_fsp == 1


# ---------------------------------------------------------------------
# Inherited areas
# ---------------------------------------------------------------------


def test_disconnect_still_present_in_v5_x(b):
    evt = b.disconnect_request(_quiet_bus(disconnect_error=1), _STATE)
    assert evt is not None


def test_crc_via_alert_n_inherited(b):
    assert b.crc(_quiet_bus(alert_n=0), _STATE) is not None


def test_low_power_split_requests_inherited(b):
    evt = b.low_power(_quiet_bus(lp_data_req=1), _STATE)
    assert evt.channel == "data"


def test_version_label(b):
    assert b.version_label == "v5.2"


def test_stateless(b):
    assert b.__dict__ == {}
