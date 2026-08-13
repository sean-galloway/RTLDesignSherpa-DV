"""LPDDR5 (JESD209-5C Table 201) and LPDDR6 (JESD209-6 Table 254) CA maps.

Golden vectors are hand-derived from the truth tables: bit i of an
edge value is CAi, H=1, L=0, V/X bits 0. LPDDR5 edges are (R1, F1);
LPDDR6 edges are (R1, F1, R2, F2).
"""

import pytest

from CocoTBFramework.components.dfi.ca_map import CACodec
from CocoTBFramework.components.dfi.ca_transport import pack_ddr_cmdaddr
from CocoTBFramework.components.dfi.lpddr5_ca_map import (
    LPDDR5_CA_MAP_8B,
    LPDDR5_CA_MAP_16B,
    LPDDR5_CA_MAP_BG,
    LPDDR5_CA_WIDTH,
    lpddr5_ca_map,
)
from CocoTBFramework.components.dfi.lpddr6_ca_map import (
    LPDDR6_CA_MAP,
    LPDDR6_CA_WIDTH,
)

LP5_BG = CACodec(LPDDR5_CA_MAP_BG)
LP5_16B = CACodec(LPDDR5_CA_MAP_16B)
LP5_8B = CACodec(LPDDR5_CA_MAP_8B)
LP6 = CACodec(LPDDR6_CA_MAP)


# ===========================================================================
# LPDDR5 — JESD209-5C Table 201
# ===========================================================================

def test_lpddr5_r1_opcodes_golden():
    """R1 CA[6:0] patterns straight off the truth table."""
    assert LP5_16B.encode("nop")[0] == 0b0000000
    assert LP5_16B.encode("pde")[0] == 0b1000000
    assert LP5_16B.encode("act2", row_lo=0)[0] == 0b0000011
    assert LP5_16B.encode("act1", ba=0, row_hi=0)[0] == 0b0000111
    assert LP5_16B.encode("pre", ba=0, ab=0)[0] == 0b1111000
    assert LP5_16B.encode("ref", ba=0, ab=0)[0] == 0b0111000
    assert LP5_16B.encode("mwr", ba=0, col=0, ap=0)[0] == 0b0000010
    assert LP5_16B.encode("wr16", ba=0, col=0, ap=0)[0] == 0b0000110
    assert LP5_16B.encode("rd16", ba=0, col=0, ap=0)[0] == 0b0000001
    assert LP5_16B.encode("rd32", ba=0, col=0, ap=0)[0] == 0b0000101
    assert LP5_16B.encode("wr32", ba=0, col=0, ap=0)[0] == 0b0000100
    assert LP5_16B.encode("cas")[0] == 0b0001100
    assert LP5_16B.encode("mpc", op=0)[0] == 0b0110000
    assert LP5_16B.encode("sre", dsm=0, pd=0)[0] == 0b1101000
    assert LP5_16B.encode("srx")[0] == 0b0101000
    assert LP5_16B.encode("mrw1", ma=0)[0] == 0b1011000
    assert LP5_16B.encode("mrw2", op=0)[0] == 0b0001000
    assert LP5_16B.encode("mrr", ma=0)[0] == 0b0011000
    assert LP5_16B.encode("wff")[0] == 0b1100000
    assert LP5_16B.encode("rff")[0] == 0b0100000
    assert LP5_16B.encode("rdc")[0] == 0b1010000


def test_lpddr5_act_row_split():
    # ACT-1 F1 CA4-CA6 = R11-R13, R1 CA3-CA6 = R14-R17.
    r1, f1 = LP5_16B.encode("act1", ba=0, row_hi=0b1111111)
    assert r1 == 0b1111111 and f1 == 0b1110000
    # ACT-2 F1 CA0-CA6 = R0-R6, R1 CA3-CA6 = R7-R10.
    r1, f1 = LP5_16B.encode("act2", row_lo=0x7FF)
    assert r1 == 0b1111011 and f1 == 0b1111111
    # Round-trip the full 18-bit row through the command pair.
    row = 0x2A5A5
    _, hi = LP5_16B.decode(LP5_16B.encode("act1", ba=3,
                                          row_hi=(row >> 11) & 0x7F))
    _, lo = LP5_16B.decode(LP5_16B.encode("act2", row_lo=row & 0x7FF))
    assert (hi["row_hi"] << 11) | lo["row_lo"] == row


def test_lpddr5_bank_org_layouts():
    """The F1 bank row differs per organization (Table 201)."""
    # 16B: BA[3:0] on F1 CA[3:0]
    assert LP5_16B.encode("pre", ba=0b1011, ab=0)[1] == 0b0001011
    # BG: BA[1:0] on CA[1:0], BG[1:0] on CA[3:2]
    assert LP5_BG.encode("pre", ba=0b11, bg=0b10, ab=0)[1] == 0b0001011
    # 8B: BA[2:0] only, CA3 is V
    assert LP5_8B.encode("pre", ba=0b101, ab=0)[1] == 0b0000101
    # AB rides F1 CA6 in every organization
    assert LP5_8B.encode("pre", ba=0, ab=1)[1] == 1 << 6


def test_lpddr5_ref_rfm_drfm_split_on_f1():
    """REF/RFM/DRFM share an R1 pattern; F1 CA3 and CA5 split them."""
    r1_ref = LP5_16B.encode("ref", ba=0, ab=0)[0]
    assert LP5_16B.encode("rfm", ba=0, sb0=0, ab=0)[0] == r1_ref
    assert LP5_16B.encode("drfm", ba=0)[0] == r1_ref
    assert LP5_16B.encode("ref", ba=0, ab=0)[1] & (1 << 3) == 0
    assert LP5_16B.encode("rfm", ba=0, sb0=0, ab=0)[1] == 1 << 3
    assert LP5_16B.encode("drfm", ba=0)[1] == (1 << 3) | (1 << 5)
    for name, kw in (("ref", dict(ba=5, ab=1)),
                     ("rfm", dict(ba=3, sb0=1, ab=0)),
                     ("drfm", dict(ba=0b1101))):
        got, f = LP5_16B.decode(LP5_16B.encode(name, **kw))
        assert (got, f) == (name, kw)


def test_lpddr5_drfm_bank_bit_moves_to_ca4():
    # 16B: BA[2:0] on F1 CA[2:0], BA3 on F1 CA4.
    assert LP5_16B.encode("drfm", ba=0b1000)[1] == (1 << 3) | (1 << 4) \
        | (1 << 5)
    # BG: BG1 rides CA4 instead of CA3.
    assert LP5_BG.encode("drfm", ba=0, bg=0b10)[1] == (1 << 3) | (1 << 4) \
        | (1 << 5)


def test_lpddr5_column_layout():
    # MWR/WR16/RD16: C0 at R1 CA3, C3-C5 at R1 CA4-CA6, C1-C2 at F1 CA4-5.
    r1, f1 = LP5_16B.encode("wr16", ba=0, col=0b111111, ap=0)
    assert r1 == 0b1111110 and f1 == 0b0110000
    # WR32 has no C0: field bit 0 is C1.
    r1, f1 = LP5_16B.encode("wr32", ba=0, col=0b11111, ap=0)
    assert r1 == 0b1110100 and f1 == 0b0110000
    # AP rides F1 CA6.
    assert LP5_16B.encode("rd16", ba=0, col=0, ap=1)[1] == 1 << 6


def test_lpddr5_8b_read_carries_b4():
    """In 8B mode F1 CA3 is burst-start B4, not a bank bit (note 10)."""
    assert "b4" in {f.name for f in
                    LPDDR5_CA_MAP_8B.command("rd16").fields}
    assert LP5_8B.encode("rd16", ba=0, col=0, ap=0, b4=1)[1] == 1 << 3
    with pytest.raises(ValueError):
        LP5_16B.encode("rd16", ba=0, col=0, ap=0, b4=1)


def test_lpddr5_wide_only_commands_absent_in_8b():
    """WR32/RD32 are BG/16B-only (notes 8, 11); DRFM has no 8B row."""
    for name in ("wr32", "rd32", "drfm"):
        LPDDR5_CA_MAP_16B.command(name)
        with pytest.raises(KeyError):
            LPDDR5_CA_MAP_8B.command(name)


def test_lpddr5_operand_fields():
    assert LP5_16B.encode("sre", dsm=1, pd=0)[1] == 1 << 5
    assert LP5_16B.encode("sre", dsm=0, pd=1)[1] == 1 << 6
    assert LP5_16B.encode("rfm", ba=0, sb0=1, ab=0)[1] & (1 << 4)
    # MPC/MRW-2 op: OP0-6 on F1, OP7 on R1 CA6.
    r1, f1 = LP5_16B.encode("mpc", op=0xFF)
    assert r1 == 0b1110000 and f1 == 0b1111111
    # CAS operands
    r1, f1 = LP5_16B.encode("cas", ws_wr=1, ws_rd=0, ws_fs=1,
                            dc=0b1010, wrx=1, wxsa=0, wxsb_b3=1)
    assert r1 == 0b1011100 and f1 == 0b1011010


def test_lpddr5_pre_mode_variants():
    """MR75-gated address-sample variants (notes 14, 15)."""
    base = lpddr5_ca_map("16B")
    no_sample = lpddr5_ca_map("16B", pre_mode="no_sample")
    sample = lpddr5_ca_map("16B", pre_mode="sample")
    assert "ab" in {f.name for f in base.command("pre").fields}
    # The variants pin F1 CA6=L and set CA5 per MR75 OP[3].
    assert CACodec(no_sample).encode("pre", ba=0)[1] == 0
    assert CACodec(sample).encode("pre", ba=0)[1] == 1 << 5
    for m in (no_sample, sample):
        assert "ab" not in {f.name for f in m.command("pre").fields}


@pytest.mark.parametrize("codec,name,kw", [
    (LP5_16B, "nop", {}),
    (LP5_16B, "pde", {}),
    (LP5_16B, "act1", dict(ba=0b1010, row_hi=0b1010101)),
    (LP5_16B, "act2", dict(row_lo=0x5A5)),
    (LP5_16B, "pre", dict(ba=0b0110, ab=1)),
    (LP5_16B, "mwr", dict(ba=0b1111, col=0b101010, ap=1)),
    (LP5_16B, "wr16", dict(ba=0b0001, col=0b010101, ap=0)),
    (LP5_16B, "wr32", dict(ba=0b1100, col=0b10110, ap=1)),
    (LP5_16B, "rd16", dict(ba=0b0011, col=0b110011, ap=1)),
    (LP5_16B, "rd32", dict(ba=0b1001, col=0b001100, ap=0)),
    (LP5_16B, "cas", dict(ws_wr=0, ws_rd=1, ws_fs=0, dc=0b0101,
                          wrx=0, wxsa=1, wxsb_b3=0)),
    (LP5_16B, "mpc", dict(op=0xA5)),
    (LP5_16B, "sre", dict(dsm=1, pd=0)),
    (LP5_16B, "srx", {}),
    (LP5_16B, "mrw1", dict(ma=0x5A)),
    (LP5_16B, "mrw2", dict(op=0x3C)),
    (LP5_16B, "mrr", dict(ma=0x2D)),
    (LP5_16B, "wff", {}), (LP5_16B, "rff", {}), (LP5_16B, "rdc", {}),
    (LP5_BG, "pre", dict(ba=0b10, bg=0b01, ab=0)),
    (LP5_BG, "ref", dict(ba=0b11, bg=0b1, ab=1)),
    (LP5_BG, "wr16", dict(ba=0b01, bg=0b11, col=0b111000, ap=1)),
    (LP5_8B, "rd16", dict(ba=0b110, col=0b011011, ap=0, b4=1)),
    (LP5_8B, "ref", dict(ba=0b101, ab=0)),
])
def test_lpddr5_decode_roundtrip(codec, name, kw):
    got, fields = codec.decode(codec.encode(name, **kw))
    assert (got, fields) == (name, kw)


def test_lpddr5_transport_pairs_the_phases():
    """One LPDDR5 command = one dfi_cmdaddr word (v6.0 Table 15)."""
    r1, f1 = LP5_16B.encode("wr16", ba=0b1010, col=0b101010, ap=1)
    word = pack_ddr_cmdaddr(LPDDR5_CA_WIDTH, rise=r1, fall=f1)
    assert word == (f1 << 7) | r1
    assert word < 1 << 14


# ===========================================================================
# LPDDR6 — JESD209-6 Table 254
# ===========================================================================

def test_lpddr6_r1_f1_opcodes_golden():
    """R1 CA[2:0] groups, then F1 CA[2:0] within each group."""
    # R1 = L L L family
    assert LP6.encode("nop")[:2] == [0b0000, 0b0000]
    assert LP6.encode("pde")[:2] == [0b0000, 0b0010]
    assert LP6.encode("sre", pd=0)[:2] == [0b0000, 0b0100]
    assert LP6.encode("srx")[:2] == [0b0000, 0b0110]
    assert LP6.encode("pre", ba=0, bg=0, sc=0, ab=0)[:2] == \
        [0b0000, 0b0011]
    assert LP6.encode("ref", ba=0, bg=0, sc=0, rfm=0, dbg=0,
                      ab=0)[:2] == [0b0000, 0b0001]
    # R1 = H H H (activate pair) splits on F1 CA0
    assert LP6.encode("act1", ba=0, bg=0, sc=0, row_hi=0)[:2] == \
        [0b0111, 0b0001]
    assert LP6.encode("act2", row_lo=0)[:2] == [0b0111, 0b0000]
    # Column commands are distinguished at R1 alone
    kw = dict(ba=0, bg=0, ws=0, col=0, ap=0, sc=0)
    assert LP6.encode("wr_s", **kw)[0] == 0b0101
    assert LP6.encode("rd_s", **kw)[0] == 0b0011
    assert LP6.encode("rd_l", **kw)[0] == 0b0010
    assert LP6.encode("wr_l", **kw)[0] == 0b0100
    # R1 = H L L family, split on F1 CA[2:0]
    assert LP6.encode("cas", ws=0, ws_off=0)[:2] == [0b0001, 0b0111]
    assert LP6.encode("mrr", ws=0, sc=0, ma=0)[:2] == [0b0001, 0b0110]
    assert LP6.encode("mpc", op=0)[:2] == [0b0001, 0b0101]
    assert LP6.encode("mrw1", ma=0, bc=0)[:2] == [0b0001, 0b0100]
    assert LP6.encode("mrw2", op=0)[:2] == [0b0001, 0b0011]
    assert LP6.encode("wff", ws=0)[:2] == [0b0001, 0b0010]
    assert LP6.encode("rff", ws=0)[:2] == [0b0001, 0b0001]
    assert LP6.encode("rdc", ws=0)[:2] == [0b0001, 0b0000]


def test_lpddr6_banks_on_f2():
    edges = LP6.encode("pre", ba=0b11, bg=0b10, sc=0, ab=0)
    assert edges[3] == 0b1011
    assert LP6.encode("rd_s", ba=0b01, bg=0b11, ws=0, col=0,
                      ap=0, sc=0)[3] == 0b1101


def test_lpddr6_act_row_split():
    # ACT-1: R11-R14 on R2 CA[3:0], R15-R16 on F1 CA1-CA2.
    edges = LP6.encode("act1", ba=0, bg=0, sc=0, row_hi=0b111111)
    assert edges[1] == 0b0111 and edges[2] == 0b1111
    # ACT-2: R0-R3 on F2, R4-R7 on R2, R8-R10 on F1 CA1-CA3.
    edges = LP6.encode("act2", row_lo=0x7FF)
    assert edges[1] == 0b1110 and edges[2] == 0b1111 and edges[3] == 0b1111
    row = 0x1A5A
    _, hi = LP6.decode(LP6.encode("act1", ba=0, bg=0, sc=0,
                                  row_hi=(row >> 11) & 0x3F))
    _, lo = LP6.decode(LP6.encode("act2", row_lo=row & 0x7FF))
    assert (hi["row_hi"] << 11) | lo["row_lo"] == row


def test_lpddr6_column_layout():
    # C0-C1 on F1 CA[1:0], C2-C5 on R2 CA[3:0]; AP on F1 CA2.
    edges = LP6.encode("wr_s", ba=0, bg=0, ws=0, col=0b111111,
                       ap=1, sc=0)
    assert edges[1] == 0b0111 and edges[2] == 0b1111
    # WR-L has no C0: field bit 0 is C1, and F1 CA0 is an opcode L.
    edges = LP6.encode("wr_l", ba=0, bg=0, ws=0, col=0b11111,
                       ap=0, sc=0)
    assert edges[1] == 0b0010 and edges[2] == 0b1111


def test_lpddr6_operand_fields():
    assert LP6.encode("sre", pd=1)[1] == 0b1100
    assert LP6.encode("cas", ws=1, ws_off=0)[0] == 0b1001
    assert LP6.encode("cas", ws=0, ws_off=1)[1] == 0b1111
    assert LP6.encode("mrw1", ma=0, bc=1)[1] == 0b1100
    assert LP6.encode("ref", ba=0, bg=0, sc=1, rfm=1, dbg=0,
                      ab=0)[1] == 0b1101
    assert LP6.encode("ref", ba=0, bg=0, sc=0, rfm=0, dbg=0b11,
                      ab=1)[2] == 0b1011
    # MA/OP: low nibble on F2, high nibble on R2.
    assert LP6.encode("mrr", ws=0, sc=0, ma=0xA5)[2:] == [0b1010, 0b0101]
    assert LP6.encode("mpc", op=0x3C)[2:] == [0b0011, 0b1100]


@pytest.mark.parametrize("name,kw", [
    ("nop", {}), ("pde", {}), ("srx", {}),
    ("sre", dict(pd=1)),
    ("pre", dict(ba=0b10, bg=0b01, sc=1, ab=0)),
    ("ref", dict(ba=0b11, bg=0b10, sc=0, rfm=1, dbg=0b01, ab=1)),
    ("act1", dict(ba=0b01, bg=0b11, sc=1, row_hi=0b101010)),
    ("act2", dict(row_lo=0x2A5)),
    ("wr_s", dict(ba=0b11, bg=0b00, ws=1, col=0b010101, ap=1, sc=0)),
    ("wr_l", dict(ba=0b00, bg=0b11, ws=0, col=0b10110, ap=0, sc=1)),
    ("rd_s", dict(ba=0b10, bg=0b01, ws=1, col=0b111000, ap=0, sc=1)),
    ("rd_l", dict(ba=0b01, bg=0b10, ws=0, col=0b001111, ap=1, sc=0)),
    ("cas", dict(ws=1, ws_off=1)),
    ("mrr", dict(ws=0, sc=1, ma=0x5A)),
    ("mpc", dict(op=0xC3)),
    ("mrw1", dict(ma=0x3F, bc=1)),
    ("mrw2", dict(op=0x0F)),
    ("wff", dict(ws=1)), ("rff", dict(ws=0)), ("rdc", dict(ws=1)),
])
def test_lpddr6_decode_roundtrip(name, kw):
    got, fields = LP6.decode(LP6.encode(name, **kw))
    assert (got, fields) == (name, kw)


def test_lpddr6_command_spans_two_cmdaddr_words():
    """Two clocks per command => two dfi_cmdaddr words (v6.0 Table 16)."""
    r1, f1, r2, f2 = LP6.encode("rd_s", ba=0b11, bg=0b01, ws=1,
                                col=0b101010, ap=1, sc=0)
    w0 = pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, rise=r1, fall=f1)
    w1 = pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, rise=r2, fall=f2)
    assert w0 == (f1 << 4) | r1 and w1 == (f2 << 4) | r2
    assert w0 < 1 << 8 and w1 < 1 << 8


def test_lpddr6_all_commands_are_two_clocks():
    for c in LPDDR6_CA_MAP.commands:
        assert c.n_edges == 4, c.name
