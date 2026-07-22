# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
"""Unit tests for the AXI4/AXI5/AXIL4 compliance checkers and the GAXI
completed-packet drain API that feeds them.

No simulator required: the checkers are constructed against a signal-less
mock DUT (so no GAXIMonitor instances or cocotb tasks are created), then
their validate_*/check_* methods are driven directly with hand-built packet
objects and mock signal handles.
"""

from __future__ import annotations

from types import SimpleNamespace

from CocoTBFramework.components.axi4.axi4_compliance_checker import (
    AXI4ComplianceChecker,
    AXI4ViolationType,
)
from CocoTBFramework.components.axi5.axi5_compliance_checker import (
    AXI5ComplianceChecker,
    AXI5ViolationType,
)
from CocoTBFramework.components.axi5.axi5_interfaces import AXI5SlaveWrite
from CocoTBFramework.components.axil4.axil4_compliance_checker import (
    AXIL4ComplianceChecker,
    AXIL4ViolationType,
)
from CocoTBFramework.components.gaxi.gaxi_monitor_base import GAXIMonitorBase


def run(coro):
    """Drive a compliance-checker coroutine to completion synchronously.

    All validate_*/check_* coroutines never await, so a single send() must
    finish them.
    """
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("coroutine did not complete synchronously")


class Sig:
    """Mock signal handle exposing .value like a cocotb handle."""

    def __init__(self, value: int = 0):
        self.value = value


class BareDut:
    """DUT with no AXI signals: checkers init cleanly with no monitors."""


def make_axi4(**kwargs) -> AXI4ComplianceChecker:
    return AXI4ComplianceChecker(dut=BareDut(), clock=None, log=None, **kwargs)


def make_axi5(**kwargs) -> AXI5ComplianceChecker:
    return AXI5ComplianceChecker(dut=BareDut(), clock=None, log=None, **kwargs)


def make_axil4(**kwargs) -> AXIL4ComplianceChecker:
    return AXIL4ComplianceChecker(dut=BareDut(), clock=None, log=None, **kwargs)


def violation_types(checker) -> list:
    return [v.violation_type for v in checker.violations]


# ---------------------------------------------------------------------------
# GAXIMonitorBase completed-packet drain API
# ---------------------------------------------------------------------------

def make_drain_stub() -> GAXIMonitorBase:
    """Minimal GAXIMonitorBase instance exercising only the drain API."""
    from collections import deque

    stub = object.__new__(GAXIMonitorBase)
    stub._completed_packet_tracking = False
    stub._completedQ = deque()
    return stub


def test_drain_disabled_by_default_records_nothing():
    stub = make_drain_stub()
    stub._record_completed_packet("pkt")
    assert len(stub._completedQ) == 0


def test_drain_enable_then_record_then_drain_in_order():
    stub = make_drain_stub()
    stub.enable_completed_packet_tracking()
    stub._record_completed_packet("a")
    stub._record_completed_packet("b")
    assert stub.get_completed_packets() == ["a", "b"]
    # Destructive on the drain queue: second call is empty
    assert stub.get_completed_packets() == []


def test_drain_count_argument_partial_drain():
    stub = make_drain_stub()
    stub.enable_completed_packet_tracking()
    for pkt in ("a", "b", "c"):
        stub._record_completed_packet(pkt)
    assert stub.get_completed_packets(count=2) == ["a", "b"]
    assert stub.get_completed_packets() == ["c"]


def test_drain_auto_enables_on_first_call():
    stub = make_drain_stub()
    assert stub.get_completed_packets() == []
    assert stub._completed_packet_tracking is True
    stub._record_completed_packet("late")
    assert stub.get_completed_packets() == ["late"]


def test_drain_does_not_touch_recvq():
    """The documented `monitor._recvQ.popleft()` usage must be unaffected."""
    from collections import deque

    stub = make_drain_stub()
    stub._recvQ = deque(["x", "y"])
    stub.enable_completed_packet_tracking()
    stub._record_completed_packet("x")
    stub._record_completed_packet("y")
    assert stub.get_completed_packets() == ["x", "y"]
    assert list(stub._recvQ) == ["x", "y"]


# ---------------------------------------------------------------------------
# AXI4 compliance checker
# ---------------------------------------------------------------------------

def test_axi4_bare_dut_creates_no_monitors():
    checker = make_axi4()
    assert checker.monitors == {}
    assert checker.monitors_active is False
    assert checker.enabled is True


def test_axi4_burst_length_violation_fires():
    checker = make_axi4()
    run(checker.validate_ar_transaction(SimpleNamespace(id=0, len=300, size=2)))
    assert AXI4ViolationType.BURST_LENGTH_VIOLATION in violation_types(checker)


def test_axi4_burst_size_violation_fires():
    checker = make_axi4()
    run(checker.validate_ar_transaction(SimpleNamespace(id=0, len=0, size=8)))
    assert AXI4ViolationType.BURST_SIZE_VIOLATION in violation_types(checker)


def test_axi4_same_id_outstanding_reads_do_not_corrupt_rlast():
    """Two outstanding reads with the same ID must not overwrite each other.

    Regression: the old dict-keyed-by-ID bookkeeping made the second AR
    clobber the first, corrupting RLAST expectations.
    """
    checker = make_axi4()
    # Two reads, same ID: 1 beat then 2 beats
    run(checker.validate_ar_transaction(SimpleNamespace(id=3, len=0, size=2)))
    run(checker.validate_ar_transaction(SimpleNamespace(id=3, len=1, size=2)))
    assert len(checker.outstanding_reads[3]) == 2

    # First read: single beat, RLAST=1 -- legal
    run(checker.validate_r_transaction(SimpleNamespace(id=3, resp=0, last=1)))
    # Second read: beat 1 of 2 (RLAST=0), beat 2 of 2 (RLAST=1) -- legal
    run(checker.validate_r_transaction(SimpleNamespace(id=3, resp=0, last=0)))
    run(checker.validate_r_transaction(SimpleNamespace(id=3, resp=0, last=1)))

    assert checker.violations == []
    assert 3 not in checker.outstanding_reads


def test_axi4_rlast_mismatch_still_detected():
    checker = make_axi4()
    run(checker.validate_ar_transaction(SimpleNamespace(id=1, len=0, size=2)))
    # Single-beat burst but RLAST=0 on the only beat
    run(checker.validate_r_transaction(SimpleNamespace(id=1, resp=0, last=0)))
    assert AXI4ViolationType.RLAST_MISMATCH in violation_types(checker)


def test_axi4_b_response_retires_oldest_same_id_write():
    checker = make_axi4()
    run(checker.validate_aw_transaction(SimpleNamespace(id=5, len=0)))
    run(checker.validate_aw_transaction(SimpleNamespace(id=5, len=3)))
    assert len(checker.outstanding_writes[5]) == 2

    run(checker.validate_b_transaction(SimpleNamespace(id=5, resp=0)))
    assert len(checker.outstanding_writes[5]) == 1
    # Remaining entry is the second (4-beat) write
    assert checker.outstanding_writes[5][0]['expected_beats'] == 4

    run(checker.validate_b_transaction(SimpleNamespace(id=5, resp=0)))
    assert 5 not in checker.outstanding_writes
    assert checker.violations == []


def test_axi4_b_invalid_response_code():
    checker = make_axi4()
    run(checker.validate_b_transaction(SimpleNamespace(id=0, resp=5)))
    assert AXI4ViolationType.RESPONSE_CODE_VIOLATION in violation_types(checker)


def test_axi4_handshake_valid_dropped_detected():
    checker = make_axi4()
    dut = SimpleNamespace(arvalid=Sig(1), arready=Sig(0))
    checker.dut = dut

    run(checker.check_handshake_rules('ar'))   # cycle 1: valid, no ready
    dut.arvalid.value = 0                      # cycle 2: valid dropped, never accepted
    run(checker.check_handshake_rules('ar'))

    assert violation_types(checker) == [AXI4ViolationType.VALID_DROPPED]


def test_axi4_handshake_legal_drop_after_completion():
    checker = make_axi4()
    dut = SimpleNamespace(arvalid=Sig(1), arready=Sig(1))
    checker.dut = dut

    run(checker.check_handshake_rules('ar'))   # cycle 1: handshake completes
    dut.arvalid.value = 0
    dut.arready.value = 0
    run(checker.check_handshake_rules('ar'))   # cycle 2: legal deassertion

    assert checker.violations == []


def test_axi4_handshake_backpressure_held_valid_is_legal():
    checker = make_axi4()
    dut = SimpleNamespace(awvalid=Sig(1), awready=Sig(0))
    checker.dut = dut

    run(checker.check_handshake_rules('aw'))   # stalled
    run(checker.check_handshake_rules('aw'))   # still stalled, valid held
    dut.awready.value = 1
    run(checker.check_handshake_rules('aw'))   # accepted
    dut.awvalid.value = 0
    dut.awready.value = 0
    run(checker.check_handshake_rules('aw'))   # legal drop

    assert checker.violations == []


def test_axi4_monitor_transaction_wiring_via_drain_api():
    """Packets surfaced by get_completed_packets() reach validate_transaction."""
    checker = make_axi4()

    class MockMonitor:
        def __init__(self, packets):
            self._packets = list(packets)

        def get_completed_packets(self, count=None):
            drained, self._packets = self._packets, []
            return drained

    monitor = MockMonitor([SimpleNamespace(id=0, len=300, size=2)])
    checker.monitors = {'AR': monitor}

    # One iteration of the monitor_transactions() loop body
    for channel_name, mon in checker.monitors.items():
        assert hasattr(mon, 'get_completed_packets')
        for packet in mon.get_completed_packets():
            run(checker.validate_transaction(channel_name, packet))
            checker.stats['checks_performed'] += 1

    assert AXI4ViolationType.BURST_LENGTH_VIOLATION in violation_types(checker)
    assert checker.stats['checks_performed'] == 1
    assert checker.stats['total_ar_transactions'] == 1


# ---------------------------------------------------------------------------
# AXI5 compliance checker
# ---------------------------------------------------------------------------

def test_axi5_same_id_outstanding_reads_do_not_corrupt_rlast():
    checker = make_axi5()
    run(checker.validate_ar_transaction(SimpleNamespace(id=7, len=0, size=2)))
    run(checker.validate_ar_transaction(SimpleNamespace(id=7, len=1, size=2)))
    assert len(checker.outstanding_reads[7]) == 2

    run(checker.validate_r_transaction(SimpleNamespace(id=7, resp=0, last=1)))
    run(checker.validate_r_transaction(SimpleNamespace(id=7, resp=0, last=0)))
    run(checker.validate_r_transaction(SimpleNamespace(id=7, resp=0, last=1)))

    assert checker.violations == []
    assert 7 not in checker.outstanding_reads


def test_axi5_trace_consistency_uses_per_id_queue():
    """Same-ID writes with different TRACE values must match in FIFO order."""
    checker = make_axi5()
    run(checker.validate_aw_transaction(SimpleNamespace(id=2, len=0, trace=1)))
    run(checker.validate_aw_transaction(SimpleNamespace(id=2, len=0, trace=0)))

    # B responses in order: trace=1 then trace=0 -- both match, no violations
    run(checker.validate_b_transaction(SimpleNamespace(id=2, resp=0, trace=1)))
    run(checker.validate_b_transaction(SimpleNamespace(id=2, resp=0, trace=0)))

    assert checker.violations == []
    assert 2 not in checker.outstanding_writes


def test_axi5_trace_mismatch_detected():
    checker = make_axi5()
    run(checker.validate_aw_transaction(SimpleNamespace(id=2, len=0, trace=1)))
    run(checker.validate_b_transaction(SimpleNamespace(id=2, resp=0, trace=0)))
    assert AXI5ViolationType.TRACE_CONSISTENCY_VIOLATION in violation_types(checker)


def test_axi5_atomic_burst_length_violation():
    checker = make_axi5()
    run(checker.validate_aw_transaction(SimpleNamespace(id=0, len=1, atop=0x30)))
    assert AXI5ViolationType.ATOP_BURST_LENGTH_VIOLATION in violation_types(checker)


def test_axi5_atomic_per_id_queue_retired_by_b():
    checker = make_axi5()
    run(checker.validate_aw_transaction(SimpleNamespace(id=4, len=0, atop=0x30)))
    run(checker.validate_aw_transaction(SimpleNamespace(id=4, len=0, atop=0x10)))
    assert len(checker.atomic_transactions[4]) == 2

    run(checker.validate_b_transaction(SimpleNamespace(id=4, resp=0)))
    assert len(checker.atomic_transactions[4]) == 1
    assert checker.atomic_transactions[4][0]['atop'] == 0x10

    run(checker.validate_b_transaction(SimpleNamespace(id=4, resp=0)))
    assert 4 not in checker.atomic_transactions


def test_axi5_handshake_valid_dropped_detected():
    checker = make_axi5()
    dut = SimpleNamespace(wvalid=Sig(1), wready=Sig(0))
    checker.dut = dut

    run(checker.check_handshake_rules('w'))
    dut.wvalid.value = 0
    run(checker.check_handshake_rules('w'))

    assert violation_types(checker) == [AXI5ViolationType.VALID_DROPPED]


# ---------------------------------------------------------------------------
# AXIL4 compliance checker
# ---------------------------------------------------------------------------

def test_axil4_concurrent_read_and_write_is_legal():
    """Simultaneous ARVALID and AWVALID/WVALID must NOT be flagged: the read
    and write channels of AXI4-Lite are independent."""
    checker = make_axil4()
    # The signal-level concurrency check was removed outright
    assert not hasattr(checker, 'check_concurrent_transactions')

    # Concurrent AR + AW + W traffic through the packet path: no violations
    run(checker.validate_ar_transaction(SimpleNamespace(addr=0x10, prot=0)))
    run(checker.validate_aw_transaction(SimpleNamespace(addr=0x20, prot=0)))
    run(checker.validate_w_transaction(SimpleNamespace(data=0xAB, strb=0xF)))

    assert checker.violations == []


def test_axil4_multiple_outstanding_is_informational_not_violation():
    checker = make_axil4()
    run(checker.validate_ar_transaction(SimpleNamespace(addr=0x0, prot=0)))
    run(checker.validate_ar_transaction(SimpleNamespace(addr=0x4, prot=0)))
    run(checker.validate_aw_transaction(SimpleNamespace(addr=0x8, prot=0)))
    run(checker.validate_aw_transaction(SimpleNamespace(addr=0xC, prot=0)))

    assert checker.violations == []
    assert checker.outstanding_reads == 2
    assert checker.outstanding_writes == 2
    assert checker.stats['max_outstanding_reads'] == 2
    assert checker.stats['max_outstanding_writes'] == 2

    run(checker.validate_r_transaction(SimpleNamespace(resp=0)))
    run(checker.validate_b_transaction(SimpleNamespace(resp=0)))
    assert checker.outstanding_reads == 1
    assert checker.outstanding_writes == 1


def test_axil4_back_to_back_transfers_not_flagged_unstable():
    """VALID held across two accepted beats with different data is legal."""
    checker = make_axil4()
    dut = SimpleNamespace(wvalid=Sig(1), wready=Sig(1), wdata=Sig(0xAAAA))
    checker.dut = dut

    run(checker.check_data_stability('w'))   # beat 1 accepted
    dut.wdata.value = 0xBBBB                 # new payload on beat 2
    run(checker.check_data_stability('w'))   # beat 2 accepted

    assert checker.violations == []


def test_axil4_payload_change_while_stalled_is_flagged():
    checker = make_axil4()
    dut = SimpleNamespace(wvalid=Sig(1), wready=Sig(0), wdata=Sig(0xAAAA))
    checker.dut = dut

    run(checker.check_data_stability('w'))   # stalled: payload must hold
    dut.wdata.value = 0xBBBB                 # illegal change under stall
    run(checker.check_data_stability('w'))

    assert violation_types(checker) == [AXIL4ViolationType.DATA_UNSTABLE]


def test_axil4_addr_change_while_stalled_is_flagged_then_reset():
    checker = make_axil4()
    dut = SimpleNamespace(arvalid=Sig(1), arready=Sig(0), araddr=Sig(0x100))
    checker.dut = dut

    run(checker.check_data_stability('ar'))
    dut.araddr.value = 0x200                 # illegal change under stall
    run(checker.check_data_stability('ar'))
    assert violation_types(checker) == [AXIL4ViolationType.DATA_UNSTABLE]

    # Handshake completes, then a new transfer with a new address is legal
    dut.arready.value = 1
    run(checker.check_data_stability('ar'))
    dut.araddr.value = 0x300
    run(checker.check_data_stability('ar'))
    assert len(checker.violations) == 1


def test_axil4_valid_low_resets_stability_state():
    checker = make_axil4()
    dut = SimpleNamespace(wvalid=Sig(1), wready=Sig(0), wdata=Sig(0x1))
    checker.dut = dut

    run(checker.check_data_stability('w'))
    dut.wvalid.value = 0                     # transfer cancelled/absent
    run(checker.check_data_stability('w'))
    dut.wvalid.value = 1
    dut.wdata.value = 0x2                    # fresh transfer, new payload
    run(checker.check_data_stability('w'))

    assert checker.violations == []


def test_axil4_handshake_legal_drop_after_completion():
    checker = make_axil4()
    dut = SimpleNamespace(awvalid=Sig(1), awready=Sig(1))
    checker.dut = dut

    run(checker.check_handshake_rules('aw'))  # handshake completes
    dut.awvalid.value = 0
    dut.awready.value = 0
    run(checker.check_handshake_rules('aw'))  # legal drop

    assert checker.violations == []


def test_axil4_handshake_valid_dropped_detected():
    checker = make_axil4()
    dut = SimpleNamespace(awvalid=Sig(1), awready=Sig(0))
    checker.dut = dut

    run(checker.check_handshake_rules('aw'))
    dut.awvalid.value = 0
    run(checker.check_handshake_rules('aw'))

    assert violation_types(checker) == [AXIL4ViolationType.VALID_DROPPED]


def test_axil4_alignment_and_strobe_checks_still_fire():
    checker = make_axil4(data_width=32)
    run(checker.validate_ar_transaction(SimpleNamespace(addr=0x2, prot=0)))
    assert AXIL4ViolationType.ADDRESS_ALIGNMENT_VIOLATION in violation_types(checker)

    run(checker.validate_w_transaction(SimpleNamespace(data=0x0, strb=0x0)))
    assert AXIL4ViolationType.STROBE_VIOLATION in violation_types(checker)


def test_axil4_report_passes_on_clean_traffic():
    checker = make_axil4()
    run(checker.validate_ar_transaction(SimpleNamespace(addr=0x4, prot=0)))
    run(checker.validate_r_transaction(SimpleNamespace(resp=0)))
    report = checker.get_compliance_report()
    assert report['compliance_status'] == 'PASSED'
    assert report['total_violations'] == 0


# ---------------------------------------------------------------------------
# AXI5SlaveWrite W-routing (silently-dropped-W fix ported from AXI4)
# ---------------------------------------------------------------------------

def make_axi5_slave_write_stub() -> AXI5SlaveWrite:
    """AXI5SlaveWrite shell with just the state _w_callback touches."""
    stub = object.__new__(AXI5SlaveWrite)
    stub.log = None
    stub.pending_transactions = {}
    stub.orphaned_w_packets = []
    stub.w_transaction_queue = []
    return stub


def test_axi5_w_beat_not_dropped_when_only_complete_pending_txns():
    """Regression for the silently-dropped-W bug: a W beat arriving while
    pending_transactions holds only complete-pending-cleanup entries must be
    routed to the orphan path, not discarded."""
    slave = make_axi5_slave_write_stub()
    slave.pending_transactions = {
        0: [{'aw_packet': None, 'w_packets': [], 'expected_beats': 1,
             'complete': True, 'sequence': 0}],
    }

    w_beat = SimpleNamespace(last=1, data=0xDEAD, poison=0)
    slave._w_callback(w_beat)

    # Beat preserved as a complete queued burst for the next AW
    assert slave.w_transaction_queue == [[w_beat]]
    assert slave.orphaned_w_packets == []


def test_axi5_w_partial_beat_orphaned_when_only_complete_pending_txns():
    slave = make_axi5_slave_write_stub()
    slave.pending_transactions = {
        0: [{'aw_packet': None, 'w_packets': [], 'expected_beats': 2,
             'complete': True, 'sequence': 0}],
    }

    w_beat = SimpleNamespace(last=0, data=0x1, poison=0)
    slave._w_callback(w_beat)

    assert slave.orphaned_w_packets == [w_beat]
    assert slave.w_transaction_queue == []


def test_axi5_match_orphaned_partial_w_packets_to_new_aw():
    """Partial orphaned W beats transfer to a newly arrived AW without being
    marked complete (parity with the AXI4 implementation)."""
    slave = make_axi5_slave_write_stub()
    beat = SimpleNamespace(last=0, data=0x2, poison=0)
    slave.orphaned_w_packets = [beat]
    slave.pending_transactions = {
        1: [{'aw_packet': None, 'w_packets': [], 'expected_beats': 2,
             'complete': False, 'sequence': 1}],
    }

    slave._match_orphaned_w_packets()

    txn = slave.pending_transactions[1][0]
    assert txn['w_packets'] == [beat]
    assert txn['complete'] is False
    assert slave.orphaned_w_packets == []
