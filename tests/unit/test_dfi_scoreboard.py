"""Unit tests for DFIScoreboard.

Uses a mock slave with simple deque attributes — no cocotb required.
Verifies callback registration, polling drains correctly, counts
update, and edge cases (empty queues, duplicate poll calls, bad
callbacks).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

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
from CocoTBFramework.scoreboards.dfi_scoreboard import DFIScoreboard


@dataclass
class _MockSlave:
    """Minimal stand-in for DFISlavePHY's event-queue attributes."""

    error_events: deque = None
    crc_events: deque = None
    update_events: deque = None
    training_events: deque = None
    ca_parity_events: deque = None
    freq_change_events: deque = None
    disconnect_events: deque = None
    takeover_events: deque = None
    log: Any = None

    def __post_init__(self):
        if self.error_events       is None: self.error_events       = deque()
        if self.crc_events         is None: self.crc_events         = deque()
        if self.update_events      is None: self.update_events      = deque()
        if self.training_events    is None: self.training_events    = deque()
        if self.ca_parity_events   is None: self.ca_parity_events   = deque()
        if self.freq_change_events is None: self.freq_change_events = deque()
        if self.disconnect_events  is None: self.disconnect_events  = deque()
        if self.takeover_events    is None: self.takeover_events    = deque()


@pytest.fixture
def slave():
    return _MockSlave()


@pytest.fixture
def sb(slave):
    return DFIScoreboard(slave)


# ---------------------------------------------------------------------
# Empty queue / no-op cases
# ---------------------------------------------------------------------


def test_poll_empty_returns_zero(sb):
    assert sb.poll() == 0
    assert sb.total_events() == 0


def test_report_starts_empty(sb):
    assert sb.report() == {area: 0 for area in DFIScoreboard.AREAS}


def test_str_when_empty(sb):
    assert "total=0" in str(sb)


# ---------------------------------------------------------------------
# Per-area callbacks fire once per event
# ---------------------------------------------------------------------


def test_error_callback_fires(slave, sb):
    seen = []
    sb.on_error(seen.append)
    slave.error_events.append(ErrorEvent(kind=ErrorKind.PARITY, code=0xab))
    sb.poll()
    assert len(seen) == 1
    assert seen[0].code == 0xab


def test_crc_callback_fires(slave, sb):
    seen = []
    sb.on_crc(seen.append)
    slave.crc_events.append(CRCEvent(kind=CRCKind.DRAM_CRC))
    sb.poll()
    assert seen[0].kind == CRCKind.DRAM_CRC


def test_update_callback_fires(slave, sb):
    seen = []
    sb.on_update(seen.append)
    slave.update_events.append(
        UpdateEvent(state=UpdateState.REQUESTED, initiator="phy"),
    )
    sb.poll()
    assert seen[0].initiator == "phy"


def test_training_callback_fires(slave, sb):
    seen = []
    sb.on_training(seen.append)
    slave.training_events.append(
        TrainingEvent(phase=TrainingPhase.DQ_TRAINING),
    )
    sb.poll()
    assert seen[0].phase == TrainingPhase.DQ_TRAINING


def test_ca_parity_callback_fires(slave, sb):
    seen = []
    sb.on_ca_parity(seen.append)
    slave.ca_parity_events.append(
        CAParityEvent(parity_bit_expected=0, parity_bit_received=1),
    )
    sb.poll()
    assert seen[0].parity_bit_received == 1


def test_freq_change_callback_fires(slave, sb):
    seen = []
    sb.on_freq_change(seen.append)
    slave.freq_change_events.append(
        FreqChangeEvent(protocol=FreqChangeProtocol.ACKNOWLEDGED),
    )
    sb.poll()
    assert seen[0].protocol == FreqChangeProtocol.ACKNOWLEDGED


def test_disconnect_callback_fires(slave, sb):
    seen = []
    sb.on_disconnect(seen.append)
    slave.disconnect_events.append(
        DisconnectEvent(phase=DisconnectPhase.REQUEST),
    )
    sb.poll()
    assert seen[0].phase == DisconnectPhase.REQUEST


def test_takeover_callback_fires(slave, sb):
    seen = []
    sb.on_takeover(seen.append)
    slave.takeover_events.append(TakeoverEvent(reason="recalibration"))
    sb.poll()
    assert seen[0].reason == "recalibration"


# ---------------------------------------------------------------------
# Counts and reporting
# ---------------------------------------------------------------------


def test_counts_track_per_area(slave, sb):
    slave.error_events.extend([
        ErrorEvent(kind=ErrorKind.PARITY, code=1),
        ErrorEvent(kind=ErrorKind.CRC,    code=2),
        ErrorEvent(kind=ErrorKind.OTHER,  code=3),
    ])
    slave.crc_events.append(CRCEvent(kind=CRCKind.DRAM_CRC))
    sb.poll()
    rpt = sb.report()
    assert rpt["error"] == 3
    assert rpt["crc"] == 1
    assert rpt["update"] == 0
    assert sb.total_events() == 4


def test_poll_returns_new_event_count(slave, sb):
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    slave.crc_events.append(CRCEvent(kind=CRCKind.DRAM_CRC))
    assert sb.poll() == 2


# ---------------------------------------------------------------------
# Polling is idempotent — same event isn't reprocessed
# ---------------------------------------------------------------------


def test_double_poll_doesnt_refire_callbacks(slave, sb):
    seen = []
    sb.on_error(seen.append)
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER, code=1))
    sb.poll()
    sb.poll()
    sb.poll()
    assert len(seen) == 1


def test_new_events_between_polls_are_picked_up(slave, sb):
    seen = []
    sb.on_error(seen.append)

    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER, code=1))
    sb.poll()

    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER, code=2))
    sb.poll()

    assert [e.code for e in seen] == [1, 2]


# ---------------------------------------------------------------------
# Multiple callbacks per area
# ---------------------------------------------------------------------


def test_multiple_callbacks_all_fire(slave, sb):
    a, b = [], []
    sb.on_error(a.append)
    sb.on_error(b.append)
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    sb.poll()
    assert len(a) == 1
    assert len(b) == 1


def test_callback_exception_doesnt_break_others(slave, sb):
    """A bad callback shouldn't prevent the rest from running."""
    good = []

    def bad(_evt):
        raise RuntimeError("oops")

    sb.on_error(bad)
    sb.on_error(good.append)
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    sb.poll()  # should not raise
    assert len(good) == 1


# ---------------------------------------------------------------------
# on_any — generic sink
# ---------------------------------------------------------------------


def test_on_any_receives_area_and_event(slave, sb):
    seen = []
    sb.on_any(lambda area, evt: seen.append((area, type(evt).__name__)))

    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    slave.crc_events.append(CRCEvent(kind=CRCKind.DRAM_CRC))
    slave.takeover_events.append(TakeoverEvent(reason="foo"))
    sb.poll()

    assert ("error",    "ErrorEvent")    in seen
    assert ("crc",      "CRCEvent")      in seen
    assert ("takeover", "TakeoverEvent") in seen


# ---------------------------------------------------------------------
# reset_counts
# ---------------------------------------------------------------------


def test_reset_counts_zeroes_but_keeps_offsets(slave, sb):
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    sb.poll()
    assert sb.total_events() == 1

    sb.reset_counts()
    assert sb.total_events() == 0

    # Adding a new event after reset still works (offset preserved)
    slave.error_events.append(ErrorEvent(kind=ErrorKind.OTHER))
    sb.poll()
    assert sb.total_events() == 1   # only the new event, not double-counted
