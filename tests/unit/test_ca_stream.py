"""Streaming CA decode: cycle-driven feeding across every protocol's
different notion of how much bus a command occupies."""

import pytest

from CocoTBFramework.components.dfi.ca_map import (
    HBM4_COL_CA_MAP,
    HBM4_ROW_CA_MAP,
    CACodec,
)
from CocoTBFramework.components.dfi.ca_stream import (
    CAStream,
    HBM4CAStreams,
    args_to_legacy_addr,
)
from CocoTBFramework.components.dfi.ca_transport import (
    LPDDR5_CA_WIDTH,
    LPDDR6_CA_WIDTH,
    pack_ddr_cmdaddr,
)
from CocoTBFramework.components.dfi.ddr5_ca_map import (
    DDR5_CA_MAP,
    DDR5_CA_WIDTH,
)
from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.hbm_ca import (
    HBM4CAEdge,
    pack_hbm4_cmdaddr,
)
from CocoTBFramework.components.dfi.lpddr5_ca_map import LPDDR5_CA_MAP_16B
from CocoTBFramework.components.dfi.lpddr6_ca_map import LPDDR6_CA_MAP

# ---------------------------------------------------------------------------
# DDR5 — SDR words, commands span 1 or 2 cycles
# ---------------------------------------------------------------------------

def test_ddr5_one_cycle_command_completes_in_one_word():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    got = s.feed_word(enc.encode("preab", cid=0)[0])
    assert len(got) == 1
    assert got[0][0] is DRAMCommand.PREA
    assert not s.partial


def test_ddr5_two_cycle_command_spans_two_words():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    e0, e1 = enc.encode("act", row=0x1234, ba=2, bg=5, cid=0)
    assert s.feed_word(e0) == []          # nothing yet
    assert s.partial                      # ...mid-command across cycles
    got = s.feed_word(e1)
    assert len(got) == 1 and got[0][0] is DRAMCommand.ACT
    assert got[0][1]["row"] == 0x1234
    assert not s.partial


def test_ddr5_back_to_back_commands():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    seq = (enc.encode("act", row=7, ba=0, bg=0, cid=0)
           + enc.encode("rd", bl=1, ba=0, bg=0, cid=0, col=9)
           + enc.encode("nop"))
    out = []
    for w in seq:
        out += s.feed_word(w)
    assert [c for c, _ in out] == [DRAMCommand.ACT, DRAMCommand.RD,
                                   DRAMCommand.NOP]


# ---------------------------------------------------------------------------
# LPDDR5 — one word carries both phases, one command per word
# ---------------------------------------------------------------------------

def test_lpddr5_command_per_word():
    enc = CACodec(LPDDR5_CA_MAP_16B)
    s = CAStream(LPDDR5_CA_MAP_16B, LPDDR5_CA_WIDTH)
    r1, f1 = enc.encode("pre", ba=5, ab=0)
    got = s.feed_word(pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, r1, f1))
    assert len(got) == 1
    cmd, args = got[0]
    assert cmd is DRAMCommand.PRE and args["bank"] == 5


def test_lpddr5_split_activate_across_words():
    enc = CACodec(LPDDR5_CA_MAP_16B)
    s = CAStream(LPDDR5_CA_MAP_16B, LPDDR5_CA_WIDTH)
    row = 0x2A5A5

    def word(name, **kw):
        r1, f1 = enc.encode(name, **kw)
        return pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, r1, f1)

    # ACT-1 completes as a command but emits nothing (split first half).
    assert s.feed_word(word("act1", ba=3, row_hi=(row >> 11) & 0x7F)) == []
    assert not s.partial          # the WORD is complete; the PAIR is not
    got = s.feed_word(word("act2", row_lo=row & 0x7FF))
    assert len(got) == 1
    cmd, args = got[0]
    assert cmd is DRAMCommand.ACT
    assert (args["row"], args["bank"]) == (row, 3)


# ---------------------------------------------------------------------------
# LPDDR6 — two words (four edges) per command
# ---------------------------------------------------------------------------

def test_lpddr6_command_spans_two_words():
    enc = CACodec(LPDDR6_CA_MAP)
    s = CAStream(LPDDR6_CA_MAP, LPDDR6_CA_WIDTH)
    r1, f1, r2, f2 = enc.encode("rd_s", ba=2, bg=1, ws=0, col=0x15,
                                ap=1, sc=0)
    w0 = pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, r1, f1)
    w1 = pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, r2, f2)
    assert s.feed_word(w0) == []
    assert s.partial
    got = s.feed_word(w1)
    assert len(got) == 1
    cmd, args = got[0]
    assert cmd is DRAMCommand.RDA          # ap=1 folded in
    assert args["col"] == 0x15 and args["bank"] == (1 << 2) | 2
    assert not s.partial


def test_lpddr6_split_activate_spans_four_words():
    enc = CACodec(LPDDR6_CA_MAP)
    s = CAStream(LPDDR6_CA_MAP, LPDDR6_CA_WIDTH)
    row = 0x1A5A

    def words(name, **kw):
        e = enc.encode(name, **kw)
        return [pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[0], e[1]),
                pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[2], e[3])]

    out = []
    for w in (words("act1", ba=1, bg=3, sc=0, row_hi=(row >> 11) & 0x3F)
              + words("act2", row_lo=row & 0x7FF)):
        out += s.feed_word(w)
    assert len(out) == 1
    cmd, args = out[0]
    assert cmd is DRAMCommand.ACT
    assert args["row"] == row and args["bank"] == (3 << 2) | 1


# ---------------------------------------------------------------------------
# HBM4 — two independent streams in one word
# ---------------------------------------------------------------------------

def test_hbm4_row_and_column_lanes_decode_independently():
    row_enc = CACodec(HBM4_ROW_CA_MAP)
    col_enc = CACodec(HBM4_COL_CA_MAP)
    s = HBM4CAStreams(HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP)

    # A column WRITE (2 edges) alongside row NOPs in the same word.
    c_rise, c_fall = col_enc.encode("wr", pc=0, sid=1, ba=9, col=17)
    r_nop = row_enc.encode("rnop")[0]
    word = pack_hbm4_cmdaddr(HBM4CAEdge(row=r_nop, col=c_rise, arfu=0),
                             HBM4CAEdge(row=r_nop, col=c_fall, arfu=0))
    rows, cols = s.feed_word(word)
    assert [c for c, _ in rows] == [DRAMCommand.NOP, DRAMCommand.NOP]
    assert len(cols) == 1 and cols[0][0] is DRAMCommand.WR
    assert cols[0][1]["col"] == 17 and cols[0][1]["bank"] == 9


def test_hbm4_three_edge_activate_spans_two_words():
    row_enc = CACodec(HBM4_ROW_CA_MAP)
    col_enc = CACodec(HBM4_COL_CA_MAP)
    s = HBM4CAStreams(HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP)
    e0, e1, e2 = row_enc.encode("act", pc=1, sid=2, ba=6, row=0x2A5)
    cnop = col_enc.encode("cnop")[0]

    def w(a, b):
        return pack_hbm4_cmdaddr(HBM4CAEdge(row=a, col=cnop, arfu=0),
                                 HBM4CAEdge(row=b, col=cnop, arfu=0))

    rows, _ = s.feed_word(w(e0, e1))       # ACT edges 0,1 — incomplete
    assert rows == [] and s.row.partial
    rows, _ = s.feed_word(w(e2, row_enc.encode("rnop")[0]))
    assert len(rows) == 2                  # ACT completes, then a NOP
    assert rows[0][0] is DRAMCommand.ACT
    assert rows[0][1]["row"] == 0x2A5 and rows[0][1]["bank"] == 6


# ---------------------------------------------------------------------------
# Resync / robustness
# ---------------------------------------------------------------------------

def test_unknown_head_edge_raises_in_strict_mode():
    s = CAStream(HBM4_COL_CA_MAP, 8, sdr=True)
    with pytest.raises(ValueError):
        s.feed_edge(0b010)          # C0=L C1=H: not in Table 34


def test_unknown_head_edge_resyncs_when_not_strict():
    enc = CACodec(HBM4_COL_CA_MAP)
    s = CAStream(HBM4_COL_CA_MAP, 8, sdr=True, strict=False)
    assert s.feed_edge(0b010) is None
    assert s.resyncs == 1
    # ...and a valid command right after still decodes.
    rise, fall = enc.encode("rd", pc=0, sid=0, ba=1, col=2)
    assert s.feed_edge(rise) is None
    got = s.feed_edge(fall)
    assert got is not None and got[0] is DRAMCommand.RD


def test_reset_drops_partial_command():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    s.feed_word(enc.encode("act", row=1, ba=0, bg=0, cid=0)[0])
    assert s.partial
    s.reset()
    assert not s.partial


# ---------------------------------------------------------------------------
# Legacy (bank, addr) folding used by the BFM command handler
# ---------------------------------------------------------------------------

def test_legacy_addr_folding():
    # ACTIVATE carries the row.
    assert args_to_legacy_addr({"bank": 3, "row": 0x1234}, True) == \
        (3, 0x1234)
    # Column commands carry the column; AP rides bit 10.
    assert args_to_legacy_addr({"bank": 1, "col": 5}, False) == (1, 5)
    assert args_to_legacy_addr(
        {"bank": 1, "col": 5, "auto_precharge": True}, False) == \
        (1, 5 | (1 << 10))
    # PRE all-banks uses the same bit.
    assert args_to_legacy_addr({"bank": 0, "all_banks": True}, False) == \
        (0, 1 << 10)
