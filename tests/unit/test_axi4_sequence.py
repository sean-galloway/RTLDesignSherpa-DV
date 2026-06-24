"""Unit tests for AXI4Sequence / run_axi4_sequence (no simulator).

Locks down the burst builders' AXI4 invariants — in particular that generated
bursts never cross a 4KB boundary and never underflow the address range — plus
the three bugs fixed alongside this file (write-error visibility, alignment,
gen_data stride).
"""
import asyncio

import pytest

from CocoTBFramework.components.axi4.axi4_sequence import (
    AXI4Sequence,
    run_axi4_sequence,
)

PAGE = 4096


def crosses_4k(addr: int, nbytes: int) -> bool:
    """True if [addr, addr+nbytes) straddles a 4KB boundary (illegal AXI4)."""
    return (addr // PAGE) != ((addr + nbytes - 1) // PAGE)


def _nbytes(seq, burst) -> int:
    return burst.length * seq.bytes_per_beat


# ---------------------------------------------------------------------------
# 4KB boundary + range invariants (the headline ask)
# ---------------------------------------------------------------------------
def test_random_workload_never_crosses_4k_or_underflows():
    """Across many seeds, every random burst stays aligned, in-range, and on one page."""
    for seed in range(40):
        seq = AXI4Sequence("w", data_width=64, seed=seed)
        seq.add_random_workload(300, addr_range=(0x100, 0x40000))
        assert len(seq) == 300
        for b in seq:
            nb = _nbytes(seq, b)
            assert b.addr >= 0x100, f"seed {seed}: underflow {hex(b.addr)}"
            assert b.addr + nb <= 0x40000, f"seed {seed}: overflow {hex(b.addr)}+{nb}"
            assert not crosses_4k(b.addr, nb), \
                f"seed {seed}: 4KB cross @ {hex(b.addr)} +{nb}"


def test_random_workload_4k_safe_even_with_undersized_align():
    """Even if align_to < a burst size, bursts must not cross a 4KB page."""
    for seed in range(40):
        seq = AXI4Sequence(data_width=64, seed=seed)
        seq.add_random_workload(
            300, addr_range=(0, 0x40000),
            size_weights={512: 0.5, 1024: 0.5}, align_to=64)
        for b in seq:
            nb = _nbytes(seq, b)
            assert not crosses_4k(b.addr, nb), f"4KB cross @ {hex(b.addr)} +{nb}"
            assert b.addr % nb == 0, f"not self-aligned @ {hex(b.addr)} ({nb}B)"


def test_random_workload_tight_unaligned_range_no_underflow():
    seq = AXI4Sequence(data_width=64, seed=3)
    seq.add_random_workload(500, addr_range=(0x100, 0x10000))
    assert all(b.addr >= 0x100 for b in seq)


def test_random_workload_narrow_range_raises():
    seq = AXI4Sequence(data_width=64)
    with pytest.raises(ValueError):
        seq.add_random_workload(1, addr_range=(0, 0x80), size_weights={1024: 1.0})


def test_ddr_helpers_stay_on_page_with_aligned_base():
    seq = AXI4Sequence(data_width=64, seed=1)
    seq.add_row_hit_burst(0x2_0000, n_followups=15, burst_bytes=64)
    seq.add_bank_spray(0x0, num_banks=8, bank_stride_bytes=0x400, burst_bytes=64)
    seq.add_row_miss_pair(0x4_0FC0, row_stride_bytes=0x2000, burst_bytes=64)
    for b in seq:
        nb = _nbytes(seq, b)
        assert not crosses_4k(b.addr, nb), f"4KB cross @ {hex(b.addr)} +{nb}"


# ---------------------------------------------------------------------------
# gen_data stride tracks the bus width (32/64/128)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dw,bpb", [(32, 4), (64, 8), (128, 16)])
def test_gen_data_stride_matches_bus(dw, bpb):
    seq = AXI4Sequence(data_width=dw)
    d = seq._gen_data(4, base=0x1000, seq_idx=0, data_fn=None)
    assert [d[i] - d[i - 1] for i in range(1, 4)] == [bpb, bpb, bpb]


def test_gen_data_custom_fn_used():
    seq = AXI4Sequence(data_width=64)
    d = seq._gen_data(3, base=0, seq_idx=0, data_fn=lambda a, i: i * 10)
    assert d == [0, 10, 20]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def test_add_write_read_indices_lengths_stats():
    seq = AXI4Sequence(data_width=64)
    i0 = seq.add_write(0x0, [1, 2, 3], axid=2, tag="w")
    i1 = seq.add_read(0x40, length=2, axid=2, tag="r")
    assert (i0, i1) == (0, 1)
    assert seq.bursts[0].is_write and seq.bursts[0].length == 3
    assert seq.bursts[0].data == [1, 2, 3]
    assert not seq.bursts[1].is_write and seq.bursts[1].length == 2
    assert seq.bursts[1].data is None
    assert seq.stats["writes"] == 1 and seq.stats["reads"] == 1


def test_add_write_scalar_is_wrapped():
    seq = AXI4Sequence(data_width=64)
    seq.add_write(0x0, 0xABCD)
    assert seq.bursts[0].length == 1 and seq.bursts[0].data == [0xABCD]


# ---------------------------------------------------------------------------
# DDR pattern semantics
# ---------------------------------------------------------------------------
def test_row_hit_burst_is_column_only_increment():
    seq = AXI4Sequence(data_width=64, seed=1)
    idxs = seq.add_row_hit_burst(0x2_0000, n_followups=7, burst_bytes=64)
    assert len(idxs) == 8
    addrs = [seq.bursts[i].addr for i in idxs]
    assert addrs[0] % 64 == 0
    assert all(addrs[j] - addrs[j - 1] == 64 for j in range(1, len(addrs)))
    assert all(seq.bursts[i].tag == "row_hit" for i in idxs)


def test_bank_spray_strides_across_banks():
    seq = AXI4Sequence(data_width=64)
    idxs = seq.add_bank_spray(0x0, num_banks=8, bank_stride_bytes=0x400, burst_bytes=64)
    assert [seq.bursts[i].addr for i in idxs] == [b * 0x400 for b in range(8)]


def test_row_miss_pair_targets_different_rows():
    seq = AXI4Sequence(data_width=64)
    i0, i1 = seq.add_row_miss_pair(0x4_0000, row_stride_bytes=0x2000)
    a0, a1 = seq.bursts[i0].addr, seq.bursts[i1].addr
    assert a1 - a0 == 0x2000
    assert (a0 // 0x2000) != (a1 // 0x2000)


# ---------------------------------------------------------------------------
# filter / shuffle / reset
# ---------------------------------------------------------------------------
def test_filter_excludes_tag_and_leaves_original():
    seq = AXI4Sequence(data_width=64, seed=1)
    seq.add_random_workload(50, tag="rand")
    seq.add_row_miss_pair(0x4_0000, tag="miss")
    n_before = len(seq)
    clean = seq.filter(lambda b: b.tag != "miss")
    assert all(b.tag != "miss" for b in clean)
    assert len(clean) == n_before - 2
    assert len(seq) == n_before                      # original untouched
    assert any(b.tag == "miss" for b in seq)


def test_shuffle_preserves_multiset_and_is_reproducible():
    a = AXI4Sequence(data_width=64, seed=7)
    a.add_random_workload(40)
    before = sorted(b.addr for b in a)
    a.shuffle()
    assert sorted(b.addr for b in a) == before       # same multiset
    b1 = AXI4Sequence(data_width=64, seed=9); b1.add_random_workload(40); b1.shuffle()
    b2 = AXI4Sequence(data_width=64, seed=9); b2.add_random_workload(40); b2.shuffle()
    assert [x.addr for x in b1] == [x.addr for x in b2]


def test_reset_clears_bursts_and_stats():
    seq = AXI4Sequence(data_width=64)
    seq.add_random_workload(10)
    seq.reset()
    assert len(seq) == 0 and seq.stats["random_bursts"] == 0


# ---------------------------------------------------------------------------
# Runner — write-failure visibility, read path, missing master
# ---------------------------------------------------------------------------
class _MockWr:
    clock = None

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []

    async def write_transaction(self, addr, data, **kw):
        self.calls.append((addr, list(data)))
        return {"success": not self.fail, "error": "boom" if self.fail else None}


class _MockRd:
    clock = None

    async def read_transaction(self, addr, **kw):
        return [0xABCD] * kw.get("burst_len", 1)


def test_runner_write_failure_is_surfaced():
    seq = AXI4Sequence(data_width=64)
    seq.add_write(0x0, [1, 2])
    res = asyncio.run(run_axi4_sequence(seq, master_wr=_MockWr(fail=True)))
    assert res[0]["error"] is not None
    assert "boom" in res[0]["error"]


def test_runner_write_success_and_read_data():
    seq = AXI4Sequence(data_width=64)
    seq.add_write(0x0, [1, 2])
    seq.add_read(0x0, 2)
    res = asyncio.run(run_axi4_sequence(seq, master_wr=_MockWr(), master_rd=_MockRd()))
    assert res[0]["error"] is None and res[0]["data"] == [1, 2]
    assert res[1]["error"] is None and res[1]["data"] == [0xABCD, 0xABCD]


def test_runner_missing_master_raises():
    seq = AXI4Sequence(data_width=64)
    seq.add_write(0x0, [1])
    with pytest.raises(RuntimeError):
        asyncio.run(run_axi4_sequence(seq, master_wr=None))


# ---------------------------------------------------------------------------
# Cleanups: strb-per-bus, filter stats, shuffle chaining, row_miss data, async cb
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dw,strb", [(32, 0xF), (64, 0xFF), (128, 0xFFFF)])
def test_add_write_strb_tracks_bus_width(dw, strb):
    seq = AXI4Sequence(data_width=dw)
    seq.add_write(0x0, [1, 2])
    assert seq.bursts[0].strb == strb


def test_filter_recomputes_stats():
    seq = AXI4Sequence(data_width=64, seed=1)
    seq.add_random_workload(30, tag="random")
    seq.add_row_miss_pair(0x4_0000)                 # 2 writes, tag row_miss
    clean = seq.filter(lambda b: b.tag != "row_miss")
    assert clean.stats["writes"] + clean.stats["reads"] == len(clean)
    assert clean.stats["row_miss_pairs"] == 0
    assert clean.stats["random_bursts"] == 30


def test_shuffle_returns_self_for_chaining():
    seq = AXI4Sequence(data_width=64, seed=2)
    seq.add_random_workload(10)
    assert seq.shuffle() is seq


def test_row_miss_pair_uses_gen_data_and_data_fn():
    seq = AXI4Sequence(data_width=64)
    i0, _ = seq.add_row_miss_pair(0x1000, burst_bytes=64)
    # default write data is address-derived (_gen_data), not a literal fill
    assert seq.bursts[i0].data == seq._gen_data(seq.bursts[i0].length, 0x1000, 0, None)
    seq2 = AXI4Sequence(data_width=64)
    j0, _ = seq2.add_row_miss_pair(0x1000, burst_bytes=64, data_fn=lambda a, i: 0xC0DE)
    assert all(v == 0xC0DE for v in seq2.bursts[j0].data)


def test_async_on_burst_is_awaited():
    seen = []

    async def cb(idx, burst, result):
        seen.append(idx)

    seq = AXI4Sequence(data_width=64)
    seq.add_write(0x0, [1])
    seq.add_write(0x40, [2])
    asyncio.run(run_axi4_sequence(seq, master_wr=_MockWr(), on_burst=cb))
    assert seen == [0, 1]
