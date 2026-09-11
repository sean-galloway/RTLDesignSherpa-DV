# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for WB4Sequence (the Wishbone B4 sequence axis)."""
from __future__ import annotations

import pytest

from CocoTBFramework.components.wb4.wb4_sequence import WB4Sequence, WB4Transaction


def test_add_write_and_read_defaults():
    seq = WB4Sequence("t", addr_width=32, data_width=32)
    seq.add_write(0x100, 0xDEADBEEF).add_read(0x104)
    w, r = list(seq)
    assert (w.we, w.adr, w.dat_w, w.sel) == (1, 0x100, 0xDEADBEEF, 0xF)
    assert (r.we, r.adr, r.sel) == (0, 0x104, 0xF)
    assert w.is_write and not r.is_write


def test_widths_are_masked_not_silently_wrong():
    seq = WB4Sequence("t", addr_width=12, data_width=16)
    seq.add_write(0x1234_5678, 0xAAAA_BBBB)
    t = seq.transactions[0]
    assert t.adr == 0x678, "address must be masked to addr_width"
    assert t.dat_w == 0xBBBB, "data must be masked to data_width"
    assert t.sel == 0x3, "sel_width follows data_width/8"


def test_partial_select_is_masked():
    seq = WB4Sequence("t", data_width=32)
    seq.add_write(0, 0, sel=0xFF)
    assert seq.transactions[0].sel == 0xF


def test_seeded_sequences_are_reproducible():
    a = WB4Sequence("a", seed=7).add_random_workload(50)
    b = WB4Sequence("b", seed=7).add_random_workload(50)
    assert [(t.we, t.adr, t.dat_w, t.sel) for t in a] == \
           [(t.we, t.adr, t.dat_w, t.sel) for t in b]


def test_sequence_does_not_touch_global_random():
    import random as _r
    _r.seed(1234)
    before = _r.random()
    _r.seed(1234)
    WB4Sequence("s", seed=None).add_random_workload(100)
    assert _r.random() == before, "building a sequence perturbed the global RNG"


def test_reset_rebuilds_identically():
    seq = WB4Sequence("t", seed=3)
    seq.add_random_workload(20)
    first = [(t.we, t.adr, t.dat_w) for t in seq]
    seq.reset()
    assert len(seq) == 0
    seq.add_random_workload(20)
    assert [(t.we, t.adr, t.dat_w) for t in seq] == first


def test_write_frac_bounds():
    seq = WB4Sequence("t", seed=1)
    seq.add_random_workload(200, write_frac=1.0)
    assert seq.stats['reads'] == 0
    seq.reset()
    seq.add_random_workload(200, write_frac=0.0)
    assert seq.stats['writes'] == 0


def test_alignment_and_range():
    seq = WB4Sequence("t", data_width=32, seed=5)
    seq.add_random_workload(200, addr_lo=0x40, addr_hi=0x400, align=True)
    for t in seq:
        assert t.adr % 4 == 0, "aligned workload produced an unaligned address"
        assert 0x40 <= t.adr < 0x400


def test_windows_are_tagged_and_hit():
    seq = WB4Sequence("t", seed=11)
    seq.add_random_workload(500, addr_lo=0, addr_hi=0x1000,
                            windows=[(0xE000, 0xEFFF, 0.2), (0xF000, 0xFFFF, 0.2)])
    w0 = [t for t in seq if t.tag == "rand:w0"]
    w1 = [t for t in seq if t.tag == "rand:w1"]
    assert w0 and w1, "both windows should be drawn from at p=0.2 over 500 draws"
    assert all(0xE000 <= t.adr <= 0xEFFF for t in w0)
    assert all(0xF000 <= t.adr <= 0xFFFF for t in w1)
    base = [t for t in seq if t.tag == "rand"]
    assert all(t.adr < 0x1000 for t in base)


def test_window_probabilities_must_be_sane():
    seq = WB4Sequence("t")
    with pytest.raises(ValueError, match="sum to"):
        seq.add_random_workload(10, windows=[(0, 10, 0.7), (20, 30, 0.7)])
    with pytest.raises(ValueError, match="inverted"):
        seq.add_random_workload(10, windows=[(30, 20, 0.5)])
    with pytest.raises(ValueError, match="write_frac"):
        seq.add_random_workload(10, write_frac=1.5)
    with pytest.raises(ValueError, match="must exceed"):
        seq.add_random_workload(10, addr_lo=0x100, addr_hi=0x100)


def test_unique_addrs_never_repeats():
    seq = WB4Sequence("t", seed=2)
    seq.add_random_workload(64, addr_lo=0, addr_hi=0x400, unique_addrs=True)
    addrs = [t.adr for t in seq]
    assert len(addrs) == len(set(addrs)) == 64


def test_unique_addrs_raises_when_impossible():
    seq = WB4Sequence("t", data_width=32, seed=2)
    with pytest.raises(RuntimeError, match="unique addresses"):
        seq.add_random_workload(50, addr_lo=0, addr_hi=0x20, unique_addrs=True)


def test_readback_pairs_shape():
    seq = WB4Sequence("t", data_width=32, seed=4)
    seq.add_readback_pairs(0x200, 3)
    assert len(seq) == 6
    for i in range(3):
        w, r = seq.transactions[2 * i], seq.transactions[2 * i + 1]
        assert w.is_write and not r.is_write
        assert w.adr == r.adr == 0x200 + 4 * i


def test_strobed_writes_produce_a_partial():
    seq = WB4Sequence("t", data_width=32, seed=6)
    seq.add_strobed_writes(0, 5)
    partials = [t for t in seq if t.is_write and t.sel != 0xF]
    assert len(partials) == 5
    assert all(0 < t.sel < 0xF for t in partials)
    assert seq.stats['partial_writes'] == 5


def test_strobed_writes_need_width():
    seq = WB4Sequence("t", data_width=8)
    with pytest.raises(ValueError, match="sel_width >= 2"):
        seq.add_strobed_writes(0, 1)


def test_block_stride_and_data_cycle():
    seq = WB4Sequence("t", data_width=32)
    seq.add_block(0x10, 4, we=True, stride=8, data=[0xA, 0xB])
    assert [t.adr for t in seq] == [0x10, 0x18, 0x20, 0x28]
    assert [t.dat_w for t in seq] == [0xA, 0xB, 0xA, 0xB]


def test_filter_leaves_original_intact():
    seq = WB4Sequence("t", seed=8).add_random_workload(40)
    n = len(seq)
    writes = seq.filter(lambda t: t.is_write)
    assert len(seq) == n
    assert all(t.is_write for t in writes)
    assert len(writes) == seq.stats['writes']


def test_shuffle_is_seeded_and_keeps_membership():
    def build():
        s = WB4Sequence("t", seed=9)
        s.add_random_workload(30)
        return s
    a, b = build().shuffle(), build().shuffle()
    assert [(t.we, t.adr) for t in a] == [(t.we, t.adr) for t in b]
    plain = build()
    assert sorted((t.we, t.adr, t.dat_w) for t in a) == \
           sorted((t.we, t.adr, t.dat_w) for t in plain)


def test_to_packets_carries_fields():
    seq = WB4Sequence("t", addr_width=16, data_width=32)
    seq.add_write(0x20, 0x1234, sel=0x3).add_read(0x24)
    pkts = seq.to_packets()
    assert len(pkts) == 2
    assert int(pkts[0].we) == 1 and int(pkts[0].adr) == 0x20
    assert int(pkts[0].dat_w) == 0x1234 and int(pkts[0].sel) == 0x3
    assert int(pkts[1].we) == 0 and int(pkts[1].sel) == 0xF


def test_to_packets_rejects_a_width_mismatch():
    class FakeMaster:
        addr_width, data_width, sel_width = 32, 64, 8
    seq = WB4Sequence("t", addr_width=32, data_width=32)
    seq.add_read(0)
    with pytest.raises(ValueError, match="but the master is"):
        seq.to_packets(master=FakeMaster())


def test_stats_and_repr():
    seq = WB4Sequence("named", data_width=32, seed=1)
    seq.add_write(0, 1).add_write(0, 2, sel=0x1).add_read(4)
    s = seq.stats
    assert s == {'total': 3, 'writes': 2, 'reads': 1,
                 'unique_addrs': 2, 'partial_writes': 1,
                 'burst_transfers': 0, 'burst_ends': 0}
    assert "named" in repr(seq) and "3 transfers" in repr(seq)


def test_transaction_dataclass_is_usable_directly():
    t = WB4Transaction(we=1, adr=0x8, dat_w=0xFF, sel=0xF, tag="x")
    assert t.is_write and t.tag == "x"


# ---- burst hints ------------------------------------------------------------

def _runs(seq):
    """Split the sequence into bursts.

    A burst ends at its EOB, NOT at the next classic transfer: B4 lets one
    burst start on the clock after another ends, so splitting on classic
    transfers would silently glue two neighbouring bursts into one.
    """
    runs, cur = [], []
    for t in seq:
        if t.in_burst:
            cur.append(t)
            if t.cti == 0b111:
                runs.append(cur)
                cur = []
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def test_hints_default_to_classic_linear():
    seq = WB4Sequence("t", data_width=32)
    seq.add_write(0, 1).add_read(4)
    assert all(t.cti == 0 and t.bte == 0 and not t.in_burst for t in seq)


def test_every_burst_is_closed_by_exactly_one_end_of_burst():
    """The property a pass-through test leans on: a run of INCR always ends
    in EOB, so a hint that slipped onto a neighbouring transfer shows up as a
    burst with no end or two."""
    seq = WB4Sequence("t", data_width=32, seed=7)
    seq.add_block(0x1000, 200, we=True)
    seq.assign_burst_hints(burst_frac=0.5)
    runs = _runs(seq)
    assert runs, "burst_frac=0.5 over 200 transfers produced no bursts"
    for run in runs:
        assert run[-1].cti == 0b111, "a burst must end in EOB"
        assert all(t.cti == 0b010 for t in run[:-1]), "interior transfers are INCR"


def test_a_burst_keeps_one_burst_type_throughout():
    seq = WB4Sequence("t", data_width=32, seed=11)
    seq.add_block(0, 300)
    seq.assign_burst_hints(burst_frac=0.6)
    for run in _runs(seq):
        assert len({t.bte for t in run}) == 1, "BTE must not change mid-burst"


def test_classic_transfers_carry_the_linear_burst_type():
    seq = WB4Sequence("t", data_width=32, seed=3)
    seq.add_block(0, 100)
    seq.assign_burst_hints()
    assert all(t.bte == 0 for t in seq if not t.in_burst)


def test_hints_are_reproducible_for_a_seed():
    def build():
        s = WB4Sequence("t", data_width=32, seed=99)
        s.add_block(0, 60)
        return [(t.cti, t.bte) for t in s.assign_burst_hints()]
    assert build() == build()


def test_burst_frac_zero_leaves_every_transfer_classic():
    seq = WB4Sequence("t", data_width=32, seed=1)
    seq.add_block(0, 50)
    seq.assign_burst_hints(burst_frac=0.0)
    assert seq.stats['burst_transfers'] == 0


def test_a_burst_running_off_the_end_is_still_closed():
    """A burst the sequence never closes would be a CYC that ends mid-burst,
    which is not something a test should be asked to model."""
    seq = WB4Sequence("t", data_width=32, seed=5)
    seq.add_block(0, 40)
    seq.assign_burst_hints(burst_frac=1.0, min_len=100, max_len=100)
    assert seq.transactions[-1].cti == 0b111


def test_clear_burst_hints_restores_a_plain_bus():
    seq = WB4Sequence("t", data_width=32, seed=2)
    seq.add_block(0, 40)
    seq.assign_burst_hints(burst_frac=0.8)
    assert seq.stats['burst_transfers'] > 0
    seq.clear_burst_hints()
    assert seq.stats['burst_transfers'] == 0 and seq.stats['burst_ends'] == 0


def test_assign_burst_hints_rejects_a_nonsense_range():
    seq = WB4Sequence("t", data_width=32)
    seq.add_block(0, 4)
    with pytest.raises(ValueError):
        seq.assign_burst_hints(burst_frac=1.5)
    with pytest.raises(ValueError):
        seq.assign_burst_hints(min_len=5, max_len=2)


def test_to_packets_carries_the_hints():
    seq = WB4Sequence("t", data_width=32, seed=4)
    seq.add_block(0, 30)
    seq.assign_burst_hints(burst_frac=0.7)
    pkts = seq.to_packets()
    assert [(int(p.cti), int(p.bte)) for p in pkts] == [(t.cti, t.bte) for t in seq]


def test_stats_count_bursts_and_their_ends():
    seq = WB4Sequence("t", data_width=32, seed=8)
    seq.add_block(0, 120)
    seq.assign_burst_hints(burst_frac=0.5)
    s = seq.stats
    assert s['burst_ends'] == len(_runs(seq))
    assert s['burst_transfers'] >= s['burst_ends']
