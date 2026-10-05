"""Unit tests for the ACK-mode grant tracking in shared/arbiter_monitor.py.

Simulator-free: a bare RoundRobinArbiterMonitor is built the way
test_axis_monitor_delegation.py builds its monitors (object.__new__ plus the
attributes the production path touches) and fed synthetic per-cycle
SignalState samples through the real _process_grant_changes /
_process_ack_changes code, in the order the sampling loop calls them.

Regression focus (RTLDesignSherpa-DV #50, residual 2):

An ACK retires the grant it answers. Whatever is granted on the NEXT sample is
a new grant -- even when the grant vector did not change, because the arbiter
re-granted the same client back-to-back. The monitor recognised a new grant
only on a rising edge of "this client holds the grant", so a client re-granted
after its ACK without grant_valid ever dropping was never re-armed: one
new_grant, then thousands of cycles reported as continuations while every ACK
the client sent was reported as 'unexpected_ack' (5,009 of them in a
5,002-grant single-requester window on arbiter_round_robin_simple_ack).

Second defect in the same path: ACK was treated as an EDGE (ack vector changed
and nonzero). An ACK level held across back-to-back grants acknowledges each of
them at the DUT, but the monitor saw only the first.
"""

from __future__ import annotations

import logging
from collections import deque
from types import SimpleNamespace

import pytest

import CocoTBFramework.components.shared.arbiter_compliance as ac_module
import CocoTBFramework.components.shared.arbiter_monitor as am_module
from CocoTBFramework.components.shared.arbiter_monitor import (
    RoundRobinArbiterMonitor,
    SignalState,
)

CLK_NS = 10


@pytest.fixture(autouse=True)
def _no_simulator_time(monkeypatch):
    """Both modules call cocotb's get_sim_time; fake it outside a sim."""
    monkeypatch.setattr(ac_module, 'get_sim_time', lambda units=None: 0.0)
    monkeypatch.setattr(am_module, 'get_sim_time', lambda units=None: 0.0)


def _bare_rr_monitor(clients=4, ack_mode=True, registered_grant=True):
    """RoundRobinArbiterMonitor without a DUT, state mirroring __init__."""
    mon = object.__new__(RoundRobinArbiterMonitor)
    mon.title = 'unit'
    mon.log = logging.getLogger('test_arbiter_monitor_ack_mode')
    mon.clients = clients
    mon.ack_mode = ack_mode
    mon.is_weighted = False
    mon.is_deficit = False
    mon.registered_grant = registered_grant
    mon.clock_period_ns = CLK_NS
    mon.debug_enabled = False
    mon.compliance = ac_module.ArbiterCompliance(
        name='unit_compliance', clients=clients, arbiter_type='rr',
        ack_mode=ack_mode, log=mon.log, clock_period_ns=CLK_NS)
    mon.compliance.enable_debug(False)
    mon.transactions = deque(maxlen=1000)
    mon.pending_requests = {}
    mon.total_transactions = 0
    mon.active_request_vector = 0
    mon.block_arb_history = deque(maxlen=50)
    mon.blocked = False
    mon.last_block_transition_time = 0
    mon.arbiter_stats = {
        'total_grants': 0,
        'grants_per_client': [0] * clients,
        'avg_wait_time': 0,
        'wait_time_per_client': [0] * clients,
        'total_cycles': 0,
        'grant_sequences': [],
    }
    mon.grant_history = []
    mon._last_grant_info = {'gnt_vec': 0, 'gnt_id': 0, 'gnt_valid': False}
    mon._idle_before_grant = 0
    mon._grantless_run = 0
    mon._ack_mode_state = {
        i: {'grant_active': False, 'grant_start_time': 0,
            'waiting_for_ack': False, 'last_grant_reported': 0}
        for i in range(clients)
    } if ack_mode else {}
    # cocotb_bus Monitor._recv plumbing (callbacks, queue, event, stats)
    mon._callbacks = []
    mon._recvQ = deque()
    mon._event = None
    mon._wait_event = SimpleNamespace(set=lambda *a, **k: None, clear=lambda: None)
    mon.stats = SimpleNamespace(received_transactions=0)
    return mon


class Cycles:
    """Feed falling-edge samples to the monitor exactly as its loop does."""

    def __init__(self, mon):
        self.mon = mon
        self.t = 0
        self.prev = {'req': 0, 'ack': 0}

    def step(self, req, grant, ack=0):
        self.t += CLK_NS
        gnt_valid = grant != 0
        gnt_id = grant.bit_length() - 1 if gnt_valid else 0
        state = SignalState(
            current_time=self.t,
            req_vector=req, prev_req_vector=self.prev['req'],
            request_changed=(req != self.prev['req']),
            gnt_valid=gnt_valid, gnt_vector=grant, gnt_id=gnt_id,
            grant_changed=True,
            ack_vector=ack, prev_ack_vector=self.prev['ack'],
            ack_detected=(ack != self.prev['ack'] and ack != 0),
            block_arb=False, prev_block_arb=False, block_arb_changed=False,
            weights=0, prev_weights=0, weights_changed=False,
        )
        # Same order as _unified_signal_monitor: requests, grants, then ACKs
        if state.request_changed:
            self.mon._process_request_changes(state)
        self.mon._process_grant_changes(state)
        if self.mon.ack_mode:
            self.mon._process_ack_changes(state)
        self.prev = {'req': req, 'ack': ack}

    def finish(self):
        self.mon.compliance.run_compliance_analysis()
        return self.mon


def _types(mon):
    return [t.metadata['transaction_type'] for t in mon.transactions]


def _warnings(mon, kind):
    return [w for w in mon.compliance.protocol_warnings if w.get('type') == kind]


# =============================================================================
# Re-grant of the same client after its ACK is a NEW grant
# =============================================================================

def test_back_to_back_regrant_same_client_counts_every_grant():
    """Client 0 is the only requester; the arbiter re-grants it the cycle after
    each ACK, grant_valid never drops. Each cycle is one grant and one ACK."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0001, grant=0)                 # request lands, grant registers next
    for _ in range(5):
        c.step(req=0b0001, grant=0b0001, ack=0b0001)   # granted, ACKed same cycle
    mon = c.finish()

    assert _types(mon).count('new_grant') == 5
    assert mon.arbiter_stats['grants_per_client'][0] == 5
    assert _warnings(mon, 'unexpected_ack') == []
    assert mon.compliance.pending_acks == {}


def test_ack_one_cycle_after_grant_then_regrant():
    """Grant held one cycle without ACK, ACKed on the second, re-granted on the
    third: two grants, two ACKs, nothing unexpected."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0001, grant=0)
    c.step(req=0b0001, grant=0b0001, ack=0)          # grant 1, waiting
    c.step(req=0b0001, grant=0b0001, ack=0b0001)     # grant 1 ACKed
    c.step(req=0b0001, grant=0b0001, ack=0)          # grant 2 (re-grant), waiting
    c.step(req=0b0001, grant=0b0001, ack=0b0001)     # grant 2 ACKed
    mon = c.finish()

    assert _types(mon).count('new_grant') == 2
    assert _warnings(mon, 'unexpected_ack') == []
    assert mon.compliance.pending_acks == {}


# =============================================================================
# ACK is a sampled level, not an edge
# =============================================================================

def test_ack_level_held_across_back_to_back_grants_acks_each_one():
    """ACK bit held high for three consecutive grants to the same client.
    The DUT samples ACK every cycle, so all three grants are acknowledged."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0001, grant=0)
    for _ in range(3):
        c.step(req=0b0001, grant=0b0001, ack=0b0001)   # ack never toggles
    c.step(req=0, grant=0, ack=0)
    mon = c.finish()

    assert _types(mon).count('new_grant') == 3
    assert _warnings(mon, 'unexpected_ack') == []
    assert mon.compliance.pending_acks == {}, "every grant must be retired by its ACK"


# =============================================================================
# Shapes that already worked must keep working
# =============================================================================

def test_hand_off_without_grant_valid_dropping():
    """Clients 0 and 1 requesting; grant moves 0 -> 1 -> 0 on each ACK with
    grant_valid held high (the #50 hand-off fix). RR-compliant, no warnings."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0011, grant=0)
    c.step(req=0b0011, grant=0b0001, ack=0b0001)
    c.step(req=0b0011, grant=0b0010, ack=0b0010)
    c.step(req=0b0011, grant=0b0001, ack=0b0001)
    c.step(req=0b0011, grant=0b0010, ack=0b0010)
    mon = c.finish()

    assert _types(mon) == ['new_grant'] * 4
    assert mon.arbiter_stats['grants_per_client'][:2] == [2, 2]
    assert _warnings(mon, 'unexpected_ack') == []
    assert _warnings(mon, 'round_robin_violation') == []


def test_grant_drops_for_a_cycle_after_ack():
    """arbiter_round_robin Rule 3: ACK with only the owner requesting clears the
    grant for one cycle before it is re-issued. Two grants, two ACKs."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0001, grant=0)
    c.step(req=0b0001, grant=0b0001, ack=0b0001)
    c.step(req=0b0001, grant=0, ack=0)               # the Rule 3 bubble
    c.step(req=0b0001, grant=0b0001, ack=0b0001)
    c.step(req=0, grant=0, ack=0)
    mon = c.finish()

    assert _types(mon).count('new_grant') == 2
    assert _warnings(mon, 'unexpected_ack') == []
    assert mon.compliance.pending_acks == {}


def test_grant_held_without_ack_is_one_grant():
    """A grant waiting on its ACK for many cycles is still one grant."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0100, grant=0)
    for _ in range(6):
        c.step(req=0b0100, grant=0b0100, ack=0)
    c.step(req=0b0100, grant=0b0100, ack=0b0100)
    c.step(req=0, grant=0, ack=0)
    mon = c.finish()

    assert _types(mon).count('new_grant') == 1
    assert mon.arbiter_stats['grants_per_client'][2] == 1
    assert mon.compliance.pending_acks == {}


def test_foreign_ack_does_not_retire_the_grant_and_is_reported_once():
    """Client 2 raises ACK while client 0 holds the grant: the grant stays, and
    the stray ACK is reported once -- not once per cycle it stays high."""
    c = Cycles(_bare_rr_monitor())
    c.step(req=0b0001, grant=0)
    c.step(req=0b0001, grant=0b0001, ack=0)
    for _ in range(3):
        c.step(req=0b0001, grant=0b0001, ack=0b0100)   # foreign ACK, held
    c.step(req=0b0001, grant=0b0001, ack=0b0001)       # owner ACKs
    c.step(req=0, grant=0, ack=0)
    mon = c.finish()

    assert _types(mon).count('new_grant') == 1
    assert len(_warnings(mon, 'unexpected_ack')) == 1
    assert mon.compliance.pending_acks == {}
