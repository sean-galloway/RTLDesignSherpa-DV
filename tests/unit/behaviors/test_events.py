"""Unit tests for the behavior Event dataclasses.

Verifies the public Event types are immutable, comparable, and carry
the fields the catalog calls out. Light coverage — these are simple
dataclasses; the tests exist mostly to lock the public API.
"""

from __future__ import annotations

import dataclasses

import pytest

from CocoTBFramework.components.dfi.behaviors import (
    CAParityEvent,
    CRCEvent,
    CRCKind,
    DisconnectEvent,
    DisconnectPhase,
    ErrorEvent,
    ErrorKind,
    FreqChangeEvent,
    FreqChangeProtocol,
    TakeoverEvent,
    TrainingEvent,
    TrainingPhase,
    UpdateEvent,
    UpdateState,
)

_EVENT_TYPES = [
    CRCEvent, UpdateEvent, TakeoverEvent, DisconnectEvent,
    FreqChangeEvent, TrainingEvent, ErrorEvent, CAParityEvent,
]


@pytest.mark.parametrize("cls", _EVENT_TYPES)
def test_event_is_frozen_dataclass(cls):
    """All event types must be frozen so they can't be mutated downstream."""
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen


def test_crc_event_default_values():
    e = CRCEvent(kind=CRCKind.DRAM_CRC)
    assert e.slice_idx == 0
    assert e.timestamp_ns == 0.0


def test_update_state_enum_values():
    assert UpdateState.REQUESTED.value == "requested"
    assert UpdateState.GRANTED.value == "granted"
    assert UpdateState.DENIED.value == "denied"
    assert UpdateState.SELF_REFRESH_EXIT.value == "self_refresh_exit"


def test_takeover_event_carries_reason():
    e = TakeoverEvent(reason="recalibration", timestamp_ns=10.0)
    assert e.reason == "recalibration"


def test_disconnect_phases():
    assert {p.value for p in DisconnectPhase} == {"request", "ack", "release"}


def test_freq_change_protocol_enum():
    """The three protocols across versions: basic (v2.1), ack & nak (v4.0)."""
    assert FreqChangeProtocol.BASIC.value == "basic"
    assert FreqChangeProtocol.ACKNOWLEDGED.value == "ack"
    assert FreqChangeProtocol.NOT_ACKNOWLEDGED.value == "nak"


def test_training_phase_covers_v3_and_v4():
    phases = {p.value for p in TrainingPhase}
    # v3.0 phases
    assert "read_lvl" in phases
    assert "write_lvl" in phases
    assert "dq" in phases
    assert "ca" in phases
    # v3.1+
    assert "phy_req" in phases
    # v4.0 (LPDDR4 DB)
    assert "db" in phases


def test_error_kind_enum():
    assert {k.value for k in ErrorKind} == {
        "parity", "crc", "training_fail", "other"
    }


def test_event_equality():
    """Frozen dataclasses get __eq__ for free; verify it works as expected."""
    a = CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=2, timestamp_ns=10.0)
    b = CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=2, timestamp_ns=10.0)
    c = CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=3, timestamp_ns=10.0)
    assert a == b
    assert a != c


def test_event_is_hashable():
    """Frozen dataclasses are hashable — useful for putting events in sets."""
    e = UpdateEvent(state=UpdateState.REQUESTED, initiator="mc")
    assert hash(e)
    assert {e, e} == {e}
