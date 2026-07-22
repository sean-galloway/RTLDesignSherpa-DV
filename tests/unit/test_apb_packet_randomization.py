"""Randomization fixes for APBTransaction / APB5Transaction.

Covers two audit findings:

1. The default randomizer's ``pstrb`` bins were hardcoded for
   ``strb_width=4`` (``(15, 15), (0, 14)``); they are now derived from the
   actual ``strb_width``.
2. ``next()`` used to call ``Randomized.randomize()`` (cocotb_coverage) and
   then discard its results in favor of the FlexRandomizer — pure
   double-randomization overhead. The call was removed; ``next()`` now uses
   only the FlexRandomizer.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.apb.apb_packet import APBPacket, APBTransaction
from CocoTBFramework.components.apb5.apb5_packet import APB5Packet, APB5Transaction

NUM_SAMPLES = 50


@pytest.mark.parametrize("strb_width", [1, 2, 4, 8])
def test_apb_default_pstrb_randomization_respects_strb_width(strb_width):
    txn = APBTransaction(data_width=8 * strb_width, strb_width=strb_width)
    all_ones = (1 << strb_width) - 1
    seen = [txn.next().fields["pstrb"] for _ in range(NUM_SAMPLES)]
    assert all(0 <= v <= all_ones for v in seen), \
        f"pstrb escaped {strb_width}-bit range: {seen}"
    # The all-lanes bin is weighted 4:1 — statistically certain in 50 draws.
    assert all_ones in seen, "full-strobe bin must track strb_width"


@pytest.mark.parametrize("strb_width", [2, 8])
def test_apb5_default_pstrb_randomization_respects_strb_width(strb_width):
    txn = APB5Transaction(data_width=8 * strb_width, strb_width=strb_width)
    all_ones = (1 << strb_width) - 1
    seen = [txn.next().fields["pstrb"] for _ in range(NUM_SAMPLES)]
    assert all(0 <= v <= all_ones for v in seen)
    assert all_ones in seen


def test_apb_next_returns_packet_with_consistent_direction():
    txn = APBTransaction()
    for _ in range(NUM_SAMPLES):
        pkt = txn.next()
        assert isinstance(pkt, APBPacket)
        expected = "WRITE" if pkt.fields["pwrite"] else "READ"
        assert pkt.direction == expected


def test_apb_next_does_not_call_crv_randomize():
    """next() must not invoke the (discarded) cocotb_coverage randomize()."""
    txn = APBTransaction()

    def _boom():
        raise AssertionError("Randomized.randomize() must not be called by next()")

    txn.randomize = _boom
    pkt = txn.next()  # must succeed without touching randomize()
    assert isinstance(pkt, APBPacket)


def test_apb5_next_does_not_call_crv_randomize():
    txn = APB5Transaction()

    def _boom():
        raise AssertionError("Randomized.randomize() must not be called by next()")

    txn.randomize = _boom
    pkt = txn.next()
    assert isinstance(pkt, APB5Packet)


def test_apb_packet_copy_keeps_direction_consistent():
    """copy() must re-derive direction (base Packet.copy left it stale)."""
    pkt = APBPacket(pwrite=1, paddr=0x10, pwdata=0xAB)
    dup = pkt.copy()
    assert dup.direction == "WRITE"
    assert dup.fields["pwrite"] == 1


def test_apb5_packet_copy_keeps_direction_consistent():
    pkt = APB5Packet(pwrite=1, paddr=0x10, pwdata=0xAB)
    dup = pkt.copy()
    assert dup.direction == "WRITE"


def test_apb5_next_user_fields_respect_widths():
    txn = APB5Transaction(auser_width=2, wuser_width=3)
    for _ in range(NUM_SAMPLES):
        pkt = txn.next()
        assert 0 <= pkt.fields["pauser"] <= 3
        assert 0 <= pkt.fields["pwuser"] <= 7
