"""CXSCNTL codec, flit packing and reassembly.

The spec example is IHI 0079D Table 4-9 / IHI 0079B Table 4-3 (256-bit, two
packets per flit, 16-byte start alignment): every CXSCNTL field value in
that table is decoded and checked here, and the packet layout it shows is
reproduced by the packetizer.
"""
from __future__ import annotations

import random

import pytest

from CocoTBFramework.components.cxs import (
    CXSCntl,
    CXSConfig,
    CXSDepacketizer,
    CXSFlit,
    CXSPacket,
    CXSPacketizer,
    random_packet,
)

CFG256 = CXSConfig(issue='B', data_width=256, max_pkt_per_flit=2)


def _word(start, s0, s1, end, err, e0, e1):
    """Assemble a 256/2 CXSCNTL word from Table 4-3 field values."""
    return start | s0 << 2 | s1 << 3 | end << 4 | err << 6 | e0 << 8 | e1 << 11


# Cycle: (START, S0PTR, S1PTR, END, ENDERROR, E0PTR, E1PTR) from Table 4-3,
# '-' entries as 0
TABLE_4_3 = {
    1: (0x1, 0, 0, 0x1, 0, 0x6, 0),
    2: (0x3, 0, 1, 0x3, 0, 0x2, 0x7),
    4: (0x1, 0, 0, 0x0, 0, 0, 0),
    5: (0x1, 1, 0, 0x1, 0, 0x0, 0),
    6: (0x0, 0, 0, 0x0, 0, 0, 0),
    7: (0x0, 0, 0, 0x1, 0, 0x4, 0),
    8: (0x3, 0, 1, 0x3, 0, 0x0, 0x7),
    9: (0x3, 0, 1, 0x1, 0, 0x3, 0),
    10: (0x1, 1, 0, 0x3, 0, 0x3, 0x7),
    11: (0x3, 0, 1, 0x3, 0, 0x3, 0x7),
}


def test_table_4_3_decodes_and_is_legal():
    open_before = False
    for cyc in sorted(TABLE_4_3):
        c = CXSCntl.decode(CFG256, _word(*TABLE_4_3[cyc]))
        assert c.violations(CFG256, open_before) == [], f"cycle {cyc}"
        open_before = open_before + len(c.starts) - len(c.ends) > 0
    assert not open_before


def test_table_4_3_cycle_2_values():
    # TLPB at 0 ends byte 11 (E0PTR=2), TLPC at 16 ends byte 31 (E1PTR=7)
    c = CXSCntl.decode(CFG256, _word(*TABLE_4_3[2]))
    assert c.start_bytes(CFG256) == [0, 16] and c.end_bytes() == [11, 31]
    assert c.encode(CFG256) == _word(*TABLE_4_3[2])


def test_packetizer_reproduces_table_4_3_cycles_1_and_2():
    # TLPA = 28 bytes, TLPB = 12, TLPC = 16 (Table 4-3 cycles 1-2)
    p = CXSPacketizer(CFG256)
    p.add_all([CXSPacket(bytes([0xA] * 28)), CXSPacket(bytes([0xB] * 12)),
               CXSPacket(bytes([0xC] * 16))])
    flits = p.flush()
    assert [f.get('cntl') for f in flits] == [_word(*TABLE_4_3[1]), _word(*TABLE_4_3[2])]


def test_packetizer_continuation_matches_cycles_4_to_7():
    # TLPD = 36 bytes (cycles 4-5), TLPE = 16+32+20 = 68 bytes (cycles 5-7)
    p = CXSPacketizer(CFG256)
    p.add_all([CXSPacket(bytes([0xD] * 36)), CXSPacket(bytes([0xE] * 68))])
    flits = p.flush()
    assert [f.get('cntl') for f in flits] == [_word(*TABLE_4_3[c]) for c in (4, 5, 6, 7)]


def test_bad_cntl_words_are_reported():
    bad_start = CXSCntl.decode(CFG256, 0b10)                 # START = 0b10
    assert any('thermometer' in v for v in bad_start.violations(CFG256))
    err_no_end = CXSCntl.decode(CFG256, 0b1 | (0b01 << 6))   # ENDERROR[0] without END
    assert any('ENDERROR' in v for v in err_no_end.violations(CFG256))
    orphan_end = CXSCntl(starts=(), ends=(3,))
    assert any('never started' in v for v in orphan_end.violations(CFG256))
    gap_ok = CXSCntl(starts=(0, 1), ends=(0,))               # ends at byte 3, next at 16: legal
    assert gap_ok.violations(CFG256) == []
    early = CXSCntl(starts=(0, 1), ends=(5,))                # first ends at byte 23, second at 16
    assert any('overlaps' in v for v in early.violations(CFG256))


CONFIGS = [
    CFG256,
    CXSConfig(issue='A', data_width=512, max_pkt_per_flit=4),
    CXSConfig(issue='B', data_width=512, max_pkt_per_flit=3, has_last=True, has_prcltype=True),
    CXSConfig(issue='D', data_width=256, max_pkt_per_flit=3, start_align=4,
              srcid_width=4, tgtid_width=2),
    CXSConfig(issue='D', data_width=2048, max_pkt_per_flit=4),
]


@pytest.mark.parametrize("cfg", CONFIGS, ids=lambda c: c.short_name())
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_round_trip(cfg, seed):
    rng = random.Random(seed)
    # a second stream using only the stream fields this interface carries
    other = (1 if cfg.has_prcltype else 0, 2 if cfg.srcid_width else 0, 1 if cfg.tgtid_width else 0)
    streams = [(0, 0, 0), other] if any(other) else None
    pkts = [random_packet(cfg, rng, streams=streams, end_error_rate=0.1, keep_rate=0.2)
            for _ in range(60)]
    p = CXSPacketizer(cfg, gap_hook=(lambda pos: rng.randint(0, 2)) if cfg.start_align == 4 else None)
    p.add_all(pkts)
    flits = p.flush()
    d = CXSDepacketizer(cfg)
    for f in flits:
        d.push(f)
    assert d.violations == []
    assert d.packets == pkts
    assert not d.in_packet


def test_lite_one_packet_per_flit():
    cfg = CXSConfig.lite(data_width=72, issue='C')
    p = CXSPacketizer(cfg)
    with pytest.raises(ValueError):
        p.add(CXSPacket(bytes(8)))
    pkt = CXSPacket(bytes(range(9)))
    p.add(pkt)
    (flit,) = p.flush()
    assert 'cntl' not in flit.fields and flit.data_bytes() == pkt.payload


def test_packet_size_rules():
    with pytest.raises(ValueError):
        CXSPacketizer(CFG256).add(CXSPacket(bytes(6)))


def test_last_reflects_open_packets_and_keep_together():
    cfg = CXSConfig(issue='B', data_width=256, max_pkt_per_flit=2, has_last=True)
    p = CXSPacketizer(cfg)
    p.add_all([CXSPacket(bytes(40)),                       # spans 2 flits
               CXSPacket(bytes(8), keep_with_next=True),
               CXSPacket(bytes(32))])
    lasts = [f.get('last') for f in p.flush()]
    assert lasts[0] == 0                                    # packet open at flit end
    assert lasts[1] == 0                                    # keep_with_next
    assert lasts[-1] == 1


def test_flit_formatting_compact():
    f = CXSFlit(CFG256, data=0x1234, cntl=_word(*TABLE_4_3[2]))
    s = f.formatted(compact=True)
    assert 'start=[0, 1]' in s and 'end=[2, 7]' in s


def test_stream_field_without_a_wire_is_refused():
    with pytest.raises(ValueError, match='prcltype'):
        CXSPacketizer(CFG256).add(CXSPacket(bytes(16), prcltype=1))


# ---------------------------------------------------------------------------
# Per-stream framing (IHI 0079D 2.5.2): flits of different streams interleave
# ---------------------------------------------------------------------------
CFG_D = CXSConfig(issue='D', data_width=256, max_pkt_per_flit=2, srcid_width=8)


def _stream_flits(srcid, nflits):
    """One packet of nflits whole flits on stream srcid (START on the first,
    END at the last word on the last)."""
    out = []
    for i in range(nflits):
        c = CXSCntl(starts=(0,) if i == 0 else (), ends=(7,) if i == nflits - 1 else ())
        out.append(CXSFlit(CFG_D, data=(srcid << 8) | i, cntl=c.encode(CFG_D), srcid=srcid))
    return out


def test_interleaved_streams_reassemble_without_violations():
    a, b, c = _stream_flits(1, 4), _stream_flits(2, 3), _stream_flits(3, 2)
    order = [a[0], b[0], a[1], c[0], b[1], a[2], c[1], b[2], a[3]]
    d = CXSDepacketizer(CFG_D)
    for f in order:
        d.push(f)
    assert d.violations == []
    assert sorted(p.srcid for p in d.packets) == [1, 2, 3]
    assert [len(p.payload) for p in sorted(d.packets, key=lambda p: p.srcid)] == [128, 96, 64]
    assert not d.in_packet


def test_open_packets_are_per_stream():
    a, b = _stream_flits(1, 3), _stream_flits(2, 3)
    d = CXSDepacketizer(CFG_D)
    for f in (a[0], b[0], a[1]):
        d.push(f)
    assert d.in_packet and d.open_streams() == [(0, 1, 0), (0, 2, 0)]
    for f in (a[2], b[1], b[2]):
        d.push(f)
    assert d.violations == [] and not d.in_packet


def test_same_stream_framing_errors_still_caught():
    a = _stream_flits(1, 3)
    d = CXSDepacketizer(CFG_D)
    for f in (a[0], a[0]):          # a second START on a stream that is already open
        d.push(f)
    assert d.violations, "a START inside an open packet of the same stream must be flagged"


def test_continuous_data_forbids_insertion_mid_packet():
    cfg = CFG_D.with_(continuous=True)
    a = [CXSFlit(cfg, data=f.get('data'), cntl=f.get('cntl'), srcid=1) for f in _stream_flits(1, 3)]
    b = [CXSFlit(cfg, data=f.get('data'), cntl=f.get('cntl'), srcid=2) for f in _stream_flits(2, 1)]
    d = CXSDepacketizer(cfg)
    for f in (a[0], b[0], a[1], a[2]):
        d.push(f)
    assert any('CXSCONTINUOUSDATA' in v for v in d.violations)
