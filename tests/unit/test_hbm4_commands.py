"""HBM4 Row/Column command opcodes vs JESD270-4A Tables 33/34.

Golden vectors are hand-derived from the truth tables: bit i of an
edge value is signal Ri (row) / Ci (column), H=1, L=0, V-bits 0.
"""

import pytest

from CocoTBFramework.components.dfi.hbm4_commands import (
    ColumnCommand,
    RowCommand,
    decode_col_pair,
    decode_row_act_sequence,
    decode_row_edge,
    encode_col_mrs,
    encode_col_nop,
    encode_col_rd,
    encode_col_wr,
    encode_row_act,
    encode_row_nop,
    encode_row_pde,
    encode_row_pdx_srx,
    encode_row_preab,
    encode_row_prepb,
    encode_row_refab,
    encode_row_refpb,
    encode_row_rfmab,
    encode_row_rfmpb,
    encode_row_sre,
)


# ---------------------------------------------------------------------------
# Golden row encodings (Table 33)
# ---------------------------------------------------------------------------

def test_rnop_golden():
    # R0-R3 = H H H H
    assert encode_row_nop() == [0b0000001111]
    assert encode_row_pdx_srx() == [0b0000001111]


def test_act_golden():
    # pc=0, sid=0, ba=0b0001, row=0x7FFF (all RA bits high)
    e0, e1, e2 = encode_row_act(pc=0, sid=0, ba=0b0001, row=0x7FFF)
    # edge0: L H H PC=0 SID=00 BA0=1 -> bits: R1,R2,R6
    assert e0 == (1 << 1) | (1 << 2) | (1 << 6)
    # edge1: H H + RA8..RA14 all high on R2..R8, DRFM(R9)=0
    assert e1 == 0b0111111111 & ~0b1000000000 | 0b11
    assert e1 == (0b1111111 << 2) | 0b11
    # edge2: H H + RA0..RA7 all high on R2..R9
    assert e2 == (0xFF << 2) | 0b11


def test_prepb_preab_golden():
    # PREpb: H L L PC SID BA -> pc=1, sid=0b11, ba=0b1111
    assert encode_row_prepb(pc=1, sid=0b11, ba=0b1111)[0] == \
        0b1111110000 | 0b1000 | 0b001
    # PREab: H L H PC -> pc=0
    assert encode_row_preab(pc=0)[0] == 0b101


def test_refresh_family_golden():
    # REFpb: L L L PC SID BA
    assert encode_row_refpb(pc=0, sid=0, ba=0)[0] == 0
    assert encode_row_refpb(pc=1, sid=0, ba=0)[0] == 0b1000
    # REFab: H H L PC, R8=L
    assert encode_row_refab(pc=1)[0] == 0b1011
    # RFMab: H H L PC, R8=H — differs from REFab only in R8
    assert encode_row_rfmab(pc=1)[0] == (1 << 8) | 0b1011
    # RFMpb: L L H PC SID BA
    assert encode_row_rfmpb(pc=0, sid=0b01, ba=0b0010)[0] == \
        (1 << 2) | (0b01 << 4) | (0b0010 << 6)


def test_pde_sre_golden():
    # PDE: L H L H both edges; SRE: L H L L both edges
    assert encode_row_pde() == [0b1010, 0b1010]
    assert encode_row_sre() == [0b0010, 0b0010]


# ---------------------------------------------------------------------------
# Row decode
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("edges,cmd", [
    (encode_row_nop(), RowCommand.RNOP),
    (encode_row_prepb(1, 2, 5), RowCommand.PREPB),
    (encode_row_preab(1), RowCommand.PREAB),
    (encode_row_refpb(0, 1, 9), RowCommand.REFPB),
    (encode_row_refab(0), RowCommand.REFAB),
    (encode_row_rfmpb(1, 0, 3), RowCommand.RFMPB),
    (encode_row_rfmab(0), RowCommand.RFMAB),
    (encode_row_pde(), RowCommand.PDE),
    (encode_row_sre(), RowCommand.SRE),
])
def test_row_decode(edges, cmd):
    assert decode_row_edge(edges[0]).command is cmd


def test_row_decode_fields():
    d = decode_row_edge(encode_row_prepb(pc=1, sid=0b10, ba=0b1100)[0])
    assert (d.pc, d.sid, d.ba) == (1, 0b10, 0b1100)


@pytest.mark.parametrize("row", [0x0000, 0x7FFF, 0x5A5A, 0x2AA5])
def test_act_sequence_roundtrip(row):
    edges = encode_row_act(pc=1, sid=0b01, ba=0b0110, row=row)
    d, ra = decode_row_act_sequence(edges)
    assert d.command is RowCommand.ACT
    assert (d.pc, d.sid, d.ba) == (1, 0b01, 0b0110)
    assert ra == row


# ---------------------------------------------------------------------------
# Golden column encodings (Table 34)
# ---------------------------------------------------------------------------

def test_cnop_golden():
    assert encode_col_nop() == (0b111, 0)


def test_rd_wr_golden():
    # RD: H L H L PC SID BA0 | BA1-3 CA0-4; pc=1 sid=0 ba=0b0001 col=0
    rise, fall = encode_col_rd(pc=1, sid=0, ba=0b0001, col=0)
    assert rise == 0b10010101  # C0=H C2=H C4=PC C7=BA0
    assert fall == 0
    # WRA: C2=L C3=H
    rise, fall = encode_col_wr(pc=0, sid=0, ba=0, col=0b11111,
                               auto_precharge=True)
    assert rise == 0b00001001  # C0=H C3=H
    assert fall == 0b11111 << 3


def test_mrs_golden():
    # MRS: L L L MA4 OP5 OP6 OP7 MA0 | MA1-3 OP0-4
    rise, fall = encode_col_mrs(ma=0b10001, op=0b11100000)
    # rise: C3=MA4=1, C4=OP5=1, C5=OP6=1, C6=OP7=1, C7=MA0=1
    assert rise == 0b11111000
    assert fall == 0


@pytest.mark.parametrize("kwargs,cmd", [
    (dict(pc=0, sid=0, ba=0, col=0), ColumnCommand.RD),
    (dict(pc=1, sid=3, ba=15, col=31, auto_precharge=True), ColumnCommand.RDA),
])
def test_col_rd_decode(kwargs, cmd):
    d = decode_col_pair(*encode_col_rd(**kwargs))
    assert d.command is cmd
    assert (d.pc, d.sid, d.ba, d.col) == (
        kwargs['pc'], kwargs['sid'], kwargs['ba'], kwargs['col'])


def test_col_wr_mrs_roundtrip():
    d = decode_col_pair(*encode_col_wr(pc=1, sid=2, ba=9, col=17))
    assert d.command is ColumnCommand.WR
    assert (d.pc, d.sid, d.ba, d.col) == (1, 2, 9, 17)
    for ma in (0, 0x1F, 0x15):
        for op in (0, 0xFF, 0x5A):
            d = decode_col_pair(*encode_col_mrs(ma=ma, op=op))
            assert d.command is ColumnCommand.MRS
            assert (d.ma, d.op) == (ma, op), (ma, op, d)


def test_reserved_column_encoding_raises():
    with pytest.raises(ValueError):
        decode_col_pair(0b0000010, 0)  # C0=L C1=H: not in Table 34
