"""Unit tests for shared/arbiter_compliance.py.

These exercise the compliance logic directly with synthetic grant sequences -
no simulator. The module-level get_sim_time is monkeypatched since cocotb
raises "No simulator available!" outside a simulation.

Regression focus (audit FIX 1):
- Basic stats (grant counts / history / static-period stats) must accumulate
  on EVERY grant, regardless of compliance_sampling_rate. Previously they only
  accumulated on the NOT-checked sampling path, so with the default sampling
  rate of 1 analyze_fairness() always returned 1.0, check_starvation() flagged
  every client, and weight compliance always reported no_grants.
- ACK-mode round-robin checking was "deferred" but never actually performed;
  it now completes at ACK time via process_ack_received().
- process_ack_received() must return its warnings list (the monitor calls
  len() on the result).
- The WRR weight-compliance check performed zero checks; it now compares
  observed per-client grant shares in a sliding window against configured
  weights with a tolerance.
"""

from __future__ import annotations

import logging
from collections import namedtuple

import pytest

import CocoTBFramework.components.shared.arbiter_compliance as ac_module
from CocoTBFramework.components.shared.arbiter_compliance import ArbiterCompliance

# Minimal stand-in for arbiter_monitor.ArbiterTransaction (only the fields
# the compliance checker touches).
Txn = namedtuple('Txn', ['gnt_id', 'gnt_vector', 'timestamp', 'metadata'])


def make_txn(gnt_id, timestamp, weights=None, transaction_type='cycle_grant'):
    metadata = {'transaction_type': transaction_type}
    if weights is not None:
        metadata['current_weights'] = list(weights)
    return Txn(gnt_id=gnt_id, gnt_vector=(1 << gnt_id),
               timestamp=timestamp, metadata=metadata)


@pytest.fixture(autouse=True)
def _no_simulator_time(monkeypatch):
    """arbiter_compliance calls cocotb's get_sim_time; fake it outside a sim."""
    monkeypatch.setattr(ac_module, 'get_sim_time', lambda units=None: 0.0)


def make_compliance(arbiter_type='rr', clients=4, ack_mode=False):
    comp = ArbiterCompliance(
        name='test',
        clients=clients,
        arbiter_type=arbiter_type,
        ack_mode=ack_mode,
        log=logging.getLogger('test_arbiter_compliance'),
    )
    comp.enable_debug(False)  # silence per-grant prints/logs
    return comp


def warnings_of_type(comp, warning_type):
    return [w for w in comp.protocol_warnings if w['type'] == warning_type]


# =============================================================================
# FIX 1a: basic stats accumulate on every grant regardless of sampling rate
# =============================================================================

def test_grant_stats_accumulate_with_default_sampling_rate():
    """With the default sampling rate of 1, every grant must still be counted."""
    comp = make_compliance('rr')
    assert comp.compliance_sampling_rate == 1

    for i in range(8):
        comp.queue_transaction(make_txn(i % 4, timestamp=100 + i * 10))

    assert comp.total_grants == 8
    assert comp.grant_counts == [2, 2, 2, 2]
    assert len(comp.grant_history) == 8


def test_grant_stats_accumulate_on_sampled_path_too():
    """Stats also accumulate for transactions skipped by the sampling filter."""
    comp = make_compliance('rr')
    comp.set_compliance_sampling_rate(5)

    for i in range(10):
        comp.queue_transaction(make_txn(i % 2, timestamp=100 + i * 10))

    assert comp.total_grants == 10
    assert comp.grant_counts[0] == 5
    assert comp.grant_counts[1] == 5


def test_fairness_index_reflects_actual_distribution():
    """Even distribution -> ~1.0; fully skewed -> 1/n (Jain's index)."""
    even = make_compliance('rr')
    for i in range(8):
        even.queue_transaction(make_txn(i % 4, timestamp=100 + i * 10))
    assert even.analyze_fairness() == pytest.approx(1.0)

    skewed = make_compliance('rr')
    for i in range(8):
        skewed.queue_transaction(make_txn(0, timestamp=100 + i * 10))
    assert skewed.analyze_fairness() == pytest.approx(0.25)  # 1/n for n=4


def test_starvation_only_flags_clients_with_no_grants():
    """Only genuinely ungranted clients are starved - not every client."""
    comp = make_compliance('rr')
    for i in range(9):
        comp.queue_transaction(make_txn(i % 3, timestamp=100 + i * 10))  # clients 0-2 only

    result = comp.check_starvation()
    assert result['starved_clients'] == [3]


def test_no_duplicate_grant_history_when_fully_checked():
    """RR no-ACK full analysis must not double-count history entries."""
    comp = make_compliance('rr')
    for i in range(4):
        comp.queue_transaction(make_txn(i, timestamp=100 + i * 10))
    comp.run_compliance_analysis()

    assert len(comp.grant_history) == 4
    assert comp.total_grants == 4


# =============================================================================
# FIX 1b: ACK-mode deferred round-robin compliance checking
# =============================================================================

def test_ack_mode_compliant_sequence_reports_no_violation():
    comp = make_compliance('rr', ack_mode=True)

    # Grant client 0 (post-reset priority encoder expects 0)
    comp.queue_transaction(make_txn(0, timestamp=100, transaction_type='new_grant'),
                           active_requests=0b0011)
    comp.run_compliance_analysis()
    assert comp.process_ack_received(0b0001, timestamp=105) == []

    # Next grant with requests {0,1}: mask now expects client 1 - and gets it
    comp.queue_transaction(make_txn(1, timestamp=200, transaction_type='new_grant'),
                           active_requests=0b0011)
    comp.run_compliance_analysis()
    assert comp.process_ack_received(0b0010, timestamp=205) == []
    assert warnings_of_type(comp, 'round_robin_violation') == []


def test_ack_mode_deferred_violation_reported_at_ack_time():
    """A grant that violates RR order is flagged when its ACK arrives."""
    comp = make_compliance('rr', ack_mode=True)

    # First grant: client 0 with requests {0,1} - compliant post-reset.
    comp.queue_transaction(make_txn(0, timestamp=100, transaction_type='new_grant'),
                           active_requests=0b0011)
    comp.run_compliance_analysis()
    assert comp.process_ack_received(0b0001, timestamp=105) == []

    # Second grant: client 0 AGAIN with client 1 still requesting - violation.
    comp.queue_transaction(make_txn(0, timestamp=200, transaction_type='new_grant'),
                           active_requests=0b0011)
    comp.run_compliance_analysis()

    # Violation is deferred: nothing recorded until the ACK arrives
    assert warnings_of_type(comp, 'round_robin_violation') == []

    ack_warnings = comp.process_ack_received(0b0001, timestamp=205)
    assert len(ack_warnings) == 1  # monitor calls len() on this
    violation = ack_warnings[0]
    assert violation['type'] == 'round_robin_violation'
    assert violation['details']['expected_winner'] == 1
    assert violation['details']['actual_winner'] == 0
    # Also recorded for reporting
    assert len(warnings_of_type(comp, 'round_robin_violation')) == 1


def test_process_ack_received_returns_list_when_ack_mode_disabled():
    comp = make_compliance('rr', ack_mode=False)
    result = comp.process_ack_received(0b0001, timestamp=100)
    assert result == []
    assert len(result) == 0  # caller does len() - must never be None


def test_unexpected_ack_produces_warning():
    comp = make_compliance('rr', ack_mode=True)
    result = comp.process_ack_received(0b0100, timestamp=100)
    assert len(result) == 1
    assert result[0]['type'] == 'unexpected_ack'
    assert result[0]['client_id'] == 2


# =============================================================================
# FIX 1c: real WRR weight-compliance checking
# =============================================================================

def _feed_wrr(comp, pattern, weights, count, start_time=100):
    """Queue `count` grants following `pattern` (repeated) with fixed weights."""
    for i in range(count):
        gnt_id = pattern[i % len(pattern)]
        comp.queue_transaction(
            make_txn(gnt_id, timestamp=start_time + i * 10, weights=weights))


def test_wrr_compliant_distribution_produces_no_weight_warnings():
    """Grant shares exactly matching weights 3:1 must pass cleanly."""
    comp = make_compliance('wrr', clients=2)
    _feed_wrr(comp, pattern=[0, 0, 0, 1], weights=[3, 1], count=40)
    comp.run_compliance_analysis()

    assert warnings_of_type(comp, 'wrr_weight_violation') == []
    assert warnings_of_type(comp, 'wrr_zero_weight_grant') == []


def test_wrr_skewed_distribution_flags_share_deviation():
    """Alternating grants under 3:1 weights give client 1 a 4x over-share."""
    comp = make_compliance('wrr', clients=2)
    _feed_wrr(comp, pattern=[0, 1], weights=[3, 1], count=40)
    comp.run_compliance_analysis()

    violations = warnings_of_type(comp, 'wrr_weight_violation')
    assert violations, "expected at least one WRR share-deviation warning"
    # Client 1: expected 25%, observed 50% -> relative error 1.0 > 0.5 tolerance
    assert any(w['client_id'] == 1 for w in violations)


def test_wrr_zero_weight_client_grant_is_error():
    comp = make_compliance('wrr', clients=2)
    _feed_wrr(comp, pattern=[0], weights=[1, 0], count=5)
    comp.queue_transaction(make_txn(1, timestamp=999, weights=[1, 0]))
    comp.run_compliance_analysis()

    violations = warnings_of_type(comp, 'wrr_zero_weight_grant')
    assert len(violations) == 1
    assert violations[0]['client_id'] == 1
    assert violations[0]['severity'] == 'error'


def test_wrr_window_with_mixed_weights_is_skipped():
    """No single expected distribution exists across a weight change."""
    comp = make_compliance('wrr', clients=2)
    _feed_wrr(comp, pattern=[0], weights=[3, 1], count=10)
    _feed_wrr(comp, pattern=[0], weights=[1, 3], count=10, start_time=500)
    comp.run_compliance_analysis()

    # All grants to client 0 would violate either weight set, but the mixed
    # window must be skipped rather than checked against the wrong weights.
    assert warnings_of_type(comp, 'wrr_weight_violation') == []


def test_wrr_reset_analysis_clears_share_window():
    comp = make_compliance('wrr', clients=2)
    _feed_wrr(comp, pattern=[0, 1], weights=[3, 1], count=15)
    comp.reset_analysis()
    assert len(comp._wrr_recent_grants) == 0
    assert comp._wrr_grants_since_eval == 0


def test_wrr_static_period_weight_compliance_analyzed():
    """Static-period weight compliance sees real grant counts (not no_grants)."""
    comp = make_compliance('wrr', clients=2)
    comp.start_static_period(expected_weights=[3, 1])
    _feed_wrr(comp, pattern=[0, 0, 0, 1], weights=[3, 1], count=40)

    result = comp.analyze_weight_compliance()
    assert result['status'] == 'analyzed'
    assert result['total_grants'] == 40
    assert result['actual_grants'] == [30, 10]
    assert result['overall_compliance'] == pytest.approx(1.0)
    assert result['compliant'] is True
