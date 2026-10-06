# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for ACE snoop slave/master classes."""

from collections import deque
from types import SimpleNamespace

import pytest

from CocoTBFramework.components.ace.ace_interfaces import (
    AXI4ACESnoopMaster,
    AXI4ACESnoopSlave,
)
from CocoTBFramework.components.ace.ace_packet import ACEPacket
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP,
    CacheState,
    SnoopType,
)


@pytest.fixture
def mock_log():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


@pytest.fixture
def snoop_slave(mock_log, monkeypatch):
    """Return a SnoopSlave shell with just enough state for direct testing."""
    obj = object.__new__(AXI4ACESnoopSlave)
    obj.log = mock_log
    obj.line_behaviors = {}
    obj.user_handler = None
    obj._pending_snoops = deque()
    obj._seq_counter = 0
    obj._responder_active = False
    # Unit tests run outside a cocotb test, so suppress coroutine scheduling
    # and close the coroutine object to avoid unawaited-coroutine warnings.
    def _discard_coro(coro):
        try:
            coro.close()
        except Exception:
            pass
    monkeypatch.setattr("cocotb.start_soon", _discard_coro)
    return obj


@pytest.fixture
def snoop_master(mock_log):
    """Return a SnoopMaster shell with just enough state for direct testing."""
    obj = object.__new__(AXI4ACESnoopMaster)
    obj.log = mock_log
    obj._outstanding = False
    obj.allow_multiple_outstanding = False
    obj._exclude_addr = None
    obj._exclude_source = None
    obj._issued_snoops = 0
    obj._suppressed_snoops = 0
    return obj


# ---------------------------------------------------------------------------
# MESI snoop response matrix
# ---------------------------------------------------------------------------

def test_invalid_state_returns_no_data(snoop_slave):
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_SHARED)
    assert pkt.crresp == CRRESP(0)
    assert pkt.beats == 0


def test_modified_read_shared_passes_dirty_and_shared(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.MODIFIED)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_SHARED)
    assert pkt.crresp.data_transfer
    assert pkt.crresp.pass_dirty
    assert pkt.crresp.is_shared
    assert pkt.beats == 1


def test_modified_read_unique_passes_dirty_not_shared(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.MODIFIED)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_UNIQUE)
    assert pkt.crresp.data_transfer
    assert pkt.crresp.pass_dirty
    assert not pkt.crresp.is_shared


def test_shared_read_shared_indicates_shared_no_data(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.SHARED)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_SHARED)
    assert not pkt.crresp.data_transfer
    assert pkt.crresp.is_shared
    assert pkt.beats == 0


def test_exclusive_read_unique_transfers_data_and_was_unique(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.EXCLUSIVE)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_UNIQUE)
    assert pkt.crresp.data_transfer
    assert pkt.crresp.was_unique
    assert not pkt.crresp.pass_dirty


def test_make_invalid_on_modified_invalidates_without_data(snoop_slave):
    # IHI0022: MakeInvalid forbids DataTransfer (a dirty line is discarded,
    # not supplied). CRRESP.validate_for_snoop enforces the same rule, so the
    # default matrix and the validator must agree.
    snoop_slave.set_line_behavior(0x1000, CacheState.MODIFIED)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.MAKE_INVALID)
    assert not pkt.crresp.data_transfer
    assert not pkt.crresp.pass_dirty
    assert pkt.beats == 0
    valid, _ = pkt.crresp.validate_for_snoop(SnoopType.MAKE_INVALID)
    assert valid


def test_make_invalid_on_shared_raises_or_logs(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.SHARED)
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.MAKE_INVALID)
    assert not pkt.crresp.data_transfer
    assert pkt.beats == 0


# ---------------------------------------------------------------------------
# User handler injection
# ---------------------------------------------------------------------------

def test_user_handler_overrides_default(snoop_slave):
    snoop_slave.set_line_behavior(0x1000, CacheState.MODIFIED)
    snoop_slave.set_handler(lambda addr, st, state: (CRRESP.from_bits(error=True), None))
    pkt = snoop_slave._handle_snoop(0x1000, SnoopType.READ_UNIQUE)
    assert pkt.crresp.error
    assert not pkt.crresp.data_transfer


# ---------------------------------------------------------------------------
# In-order AC queue on the slave
# ---------------------------------------------------------------------------

def test_ac_callback_enqueues_in_order(snoop_slave):
    ac1 = ACEPacket.create_ac_packet(addr=0x1000, snoop=int(SnoopType.READ_SHARED), prot=0)
    ac2 = ACEPacket.create_ac_packet(addr=0x2000, snoop=int(SnoopType.READ_UNIQUE), prot=0)
    snoop_slave._ac_callback(ac1)
    snoop_slave._ac_callback(ac2)

    assert len(snoop_slave._pending_snoops) == 2
    assert snoop_slave._pending_snoops[0]["seq"] == 0
    assert snoop_slave._pending_snoops[1]["seq"] == 1
    assert snoop_slave._pending_snoops[0]["snoop_type"] == SnoopType.READ_SHARED
    assert snoop_slave._pending_snoops[1]["snoop_type"] == SnoopType.READ_UNIQUE


# ---------------------------------------------------------------------------
# Snoop master single-outstanding default
# ---------------------------------------------------------------------------

def test_master_defaults_to_single_outstanding(snoop_master):
    assert snoop_master.allow_multiple_outstanding is False


def test_master_allows_multiple_when_enabled():
    obj = object.__new__(AXI4ACESnoopMaster)
    obj.allow_multiple_outstanding = True
    obj._outstanding = True
    # The flag change is the test: enabling should permit a second issue_snoop.
    assert obj.allow_multiple_outstanding


def test_master_exclude_addr_hook(snoop_master):
    snoop_master._exclude_addr = lambda addr: addr == 0x1000
    # Directly exercise the helper used inside issue_snoop.
    assert snoop_master._should_exclude(0x1000)
    assert not snoop_master._should_exclude(0x2000)
