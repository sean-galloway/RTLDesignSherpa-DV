"""DDR5 CA map vs JESD79-5B Table 31, plus the v6.0 transport packers.

Golden vectors are hand-derived from the truth table: bit i of an
edge value is CAi, H=1, L=0, V/X bits 0.
"""

import pytest

from CocoTBFramework.components.dfi.ca_map import CACodec
from CocoTBFramework.components.dfi.ca_transport import (
    LPDDR5_CA_WIDTH,
    LPDDR6_CA_WIDTH,
    pack_ddr_cmdaddr,
    unpack_ddr_cmdaddr,
)
from CocoTBFramework.components.dfi.ddr5_ca_map import (
    DDR5_CA_MAP,
    DDR5_CA_WIDTH,
)

DDR5 = CACodec(DDR5_CA_MAP)


# ---------------------------------------------------------------------------
# Golden encodings (Table 31)
# ---------------------------------------------------------------------------

def test_act_golden():
    # CA0=L CA1=L R0-3 BA BG CID | R4..R17
    assert DDR5.encode("act", row=0x3FFFF, ba=3, bg=7, cid=0) == \
        [0x7FC, 0x3FFF]
    assert DDR5.encode("act", row=0, ba=0, bg=0, cid=7) == [0x3800, 0]


def test_nop_pdx_golden():
    # H H H H H
    assert DDR5.encode("nop") == [0x1F]
    assert DDR5.encode("pdx") == [0x1F]


def test_precharge_family_golden():
    assert DDR5.encode("preab", cid=0) == [0xB]
    assert DDR5.encode("presb", ba=3, cid=0) == [0x4CB]
    # CID3 rides CA5, CID0-2 ride CA11-13 on 1-cycle commands
    assert DDR5.encode("prepb", ba=2, bg=5, cid=9) == [0xDBB]


def test_refresh_family_golden():
    # REF carries CA9=H (note 23, MR58 OP[0]=1); RFM carries CA9=L
    assert DDR5.encode("refab", rir=1, cid=0) == [0x313]
    assert DDR5.encode("rfmab", cid=0) == [0x13]
    assert DDR5.encode("refsb", ba=1, rir=0, cid=0) == [0x653]
    assert DDR5.encode("rfmsb", ba=2, cid=0) == [0x493]


def test_power_state_golden():
    assert DDR5.encode("sre") == [0x217]
    assert DDR5.encode("sref") == [0x17]
    assert DDR5.encode("pde", odt=0) == [0x417]
    assert DDR5.encode("pde", odt=1) == [0xC17]


def test_mpc_vref_golden():
    assert DDR5.encode("mpc", op=0xA5) == [0x14AF]
    assert DDR5.encode("vrefca", op=0x55) == [0xAA3]
    assert DDR5.encode("vrefcs", op=0x55) == [0x1AA3]


def test_mrw_mrr_golden():
    assert DDR5.encode("mrw", mra=0xA5, op=0x5A, cw=0) == [0x14A5, 0x5A]
    assert DDR5.encode("mrw", mra=0xA5, op=0x5A, cw=1) == [0x14A5, 0x45A]
    # MRR cycle 2 pins CA[1:0]=LL (note 21)
    assert DDR5.encode("mrr", mra=0x3F, cw=1) == [0x7F5, 0x400]


def test_wr_rd_golden():
    kw = dict(bl=1, ba=1, bg=2, cid=0)
    # WR: cycle-2 CA10=H (no AP); WRA: CA10=AP=L
    assert DDR5.encode("wr", col=0xFF, wr_partial=1, **kw) == \
        [0x26D, 0xDFE]
    assert DDR5.encode("wra", col=0xFF, wr_partial=1, **kw) == \
        [0x26D, 0x9FE]
    # RD col is 9 bits (C2..C10 on cycle-2 CA0..CA8)
    assert DDR5.encode("rd", col=0x1FF, **kw) == [0x27D, 0x5FF]
    assert DDR5.encode("rda", col=0x1FF, **kw) == [0x27D, 0x1FF]


def test_wrp_golden():
    assert DDR5.encode("wrp", ba=0, bg=0, cid=0, col=0x5A) == \
        [0x29, 0xCB4]
    assert DDR5.encode("wrpa", ba=0, bg=0, cid=0, col=0x5A) == \
        [0x29, 0x8B4]


def test_cid3_rides_cycle2_ca13():
    e0, e1 = DDR5.encode("rd", bl=0, ba=0, bg=0, cid=0xF, col=0)
    assert e0 & (0x7 << 11) == 0x7 << 11
    assert e1 & (1 << 13)


# ---------------------------------------------------------------------------
# Decode — including the cycle-2 auto-precharge split
# ---------------------------------------------------------------------------

def test_ap_variants_decode_distinctly():
    kw = dict(bl=1, ba=2, bg=3, cid=5, col=0x91, wr_partial=1)
    for name in ("wr", "wra"):
        got, f = DDR5.decode(DDR5.encode(name, **kw))
        assert (got, f) == (name, kw)
    kw = dict(bl=0, ba=1, bg=6, cid=0xA, col=0x1A5)
    for name in ("rd", "rda"):
        got, f = DDR5.decode(DDR5.encode(name, **kw))
        assert (got, f) == (name, kw)


def test_streaming_match_edge_counts():
    # WR/WRA share a first cycle; match still yields the edge count.
    spec = DDR5.match(DDR5.encode("wra", bl=0, ba=0, bg=0, cid=0,
                                  col=0, wr_partial=0)[0])
    assert spec.n_edges == 2
    assert DDR5.match(DDR5.encode("refab", rir=0, cid=0)[0]).n_edges == 1


@pytest.mark.parametrize("name,kw", [
    ("act", dict(row=0x25A5A, ba=1, bg=4, cid=2)),
    ("mrw", dict(mra=0x12, op=0xC3, cw=0)),
    ("mrr", dict(mra=0x40, cw=1)),
    ("wrp", dict(ba=3, bg=1, cid=8, col=0x3C)),
    ("wrpa", dict(ba=3, bg=1, cid=8, col=0x3C)),
    ("refab", dict(rir=1, cid=0)),
    ("rfmab", dict(cid=3)),
    ("refsb", dict(ba=2, rir=1, cid=0)),
    ("rfmsb", dict(ba=1, cid=0)),
    ("preab", dict(cid=0xC)),
    ("presb", dict(ba=1, cid=0)),
    ("prepb", dict(ba=3, bg=2, cid=0)),
    ("vrefca", dict(op=0x2A)),
    ("vrefcs", dict(op=0x7F)),
    ("mpc", dict(op=0x0F)),
    ("pde", dict(odt=1)),
    ("sre", {}), ("sref", {}), ("nop", {}),
])
def test_decode_roundtrip(name, kw):
    got, fields = DDR5.decode(DDR5.encode(name, **kw))
    assert (got, fields) == (name, kw)


def test_pdx_decodes_as_nop():
    assert DDR5.decode(DDR5.encode("pdx"))[0] == "nop"


# ---------------------------------------------------------------------------
# v6.0 transport packing (Tables 15/16/18)
# ---------------------------------------------------------------------------

def test_lpddr5_transport_lanes():
    # Table 15: rise on cmdaddr[6:0], fall on [13:7]
    word = pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, rise=0x55, fall=0x2A)
    assert word == (0x2A << 7) | 0x55
    assert unpack_ddr_cmdaddr(LPDDR5_CA_WIDTH, word) == (0x55, 0x2A)


def test_lpddr6_ddr_transport_lanes():
    # Table 16: rise on cmdaddr[3:0], fall on [7:4]
    word = pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, rise=0x9, fall=0x6)
    assert word == 0x69
    assert unpack_ddr_cmdaddr(LPDDR6_CA_WIDTH, word) == (0x9, 0x6)


def test_transport_range_checks():
    with pytest.raises(ValueError):
        pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, rise=1 << 7, fall=0)
    with pytest.raises(ValueError):
        pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, rise=0, fall=1 << 7)
    with pytest.raises(ValueError):
        unpack_ddr_cmdaddr(LPDDR6_CA_WIDTH, 1 << 8)


def test_ddr5_map_width_matches_table_18():
    # Table 18: dfi_cmdaddr width == the 14-bit DDR5 CA bus (SDR)
    assert DDR5_CA_WIDTH == 14
    assert DDR5_CA_MAP.bus_width == 14
