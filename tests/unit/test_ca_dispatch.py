"""CA map -> DRAMCommand dispatch across every shipped protocol."""

import pytest

from CocoTBFramework.components.dfi.ca_dispatch import (
    TRANSLATIONS,
    CACommandDecoder,
)
from CocoTBFramework.components.dfi.ca_map import (
    HBM4_COL_CA_MAP,
    HBM4_ROW_CA_MAP,
    CACodec,
)
from CocoTBFramework.components.dfi.ddr5_ca_map import DDR5_CA_MAP
from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.lpddr5_ca_map import (
    LPDDR5_CA_MAP_16B,
    LPDDR5_CA_MAP_BG,
)
from CocoTBFramework.components.dfi.lpddr6_ca_map import LPDDR6_CA_MAP


def _pair(camap, **kw):
    """Encoder + decoder over the same map."""
    return CACodec(camap), CACommandDecoder(camap, **kw)


# ---------------------------------------------------------------------------
# DDR5 — auto-precharge and all-banks arrive as distinct commands
# ---------------------------------------------------------------------------

def test_ddr5_activate_and_column():
    enc, dec = _pair(DDR5_CA_MAP)
    cmd, args = dec.feed(enc.encode("act", row=0x1234, ba=2, bg=5, cid=0))
    assert cmd is DRAMCommand.ACT
    assert args["row"] == 0x1234
    assert args["bank"] == (5 << 2) | 2      # bg << ba_width | ba

    cmd, args = dec.feed(enc.encode("rd", bl=1, ba=1, bg=0, cid=0,
                                    col=0x55))
    assert cmd is DRAMCommand.RD
    assert args["col"] == 0x55
    assert "auto_precharge" not in args

    cmd, args = dec.feed(enc.encode("rda", bl=1, ba=1, bg=0, cid=0,
                                    col=0x55))
    assert cmd is DRAMCommand.RDA and args["auto_precharge"] is True


def test_ddr5_precharge_and_refresh_flavors():
    enc, dec = _pair(DDR5_CA_MAP)
    cmd, args = dec.feed(enc.encode("prepb", ba=3, bg=1, cid=0))
    assert cmd is DRAMCommand.PRE and "all_banks" not in args
    cmd, args = dec.feed(enc.encode("preab", cid=0))
    assert cmd is DRAMCommand.PREA and args["all_banks"] is True
    cmd, args = dec.feed(enc.encode("refab", rir=1, cid=0))
    assert cmd is DRAMCommand.REF and args["all_banks"] is True
    # RFM is refresh management — still a refresh to the state model.
    cmd, _ = dec.feed(enc.encode("rfmsb", ba=1, cid=0))
    assert cmd is DRAMCommand.REF


def test_ddr5_mode_register():
    enc, dec = _pair(DDR5_CA_MAP)
    cmd, args = dec.feed(enc.encode("mrw", mra=0x2A, op=0xC3, cw=0))
    assert cmd is DRAMCommand.MRS
    assert (args["mr_addr"], args["mr_data"]) == (0x2A, 0xC3)
    cmd, args = dec.feed(enc.encode("mrr", mra=0x11, cw=0))
    assert cmd is DRAMCommand.MRS and args["is_mrr"] is True
    assert "mr_data" not in args


def test_ddr5_power_states_and_nop():
    enc, dec = _pair(DDR5_CA_MAP)
    assert dec.feed(enc.encode("sre"))[0] is DRAMCommand.SRE
    assert dec.feed(enc.encode("pde", odt=0))[0] is DRAMCommand.PDE
    assert dec.feed(enc.encode("nop"))[0] is DRAMCommand.NOP
    # MPC has no state-model meaning -> NOP, not an error.
    assert dec.feed(enc.encode("mpc", op=0x0F))[0] is DRAMCommand.NOP


# ---------------------------------------------------------------------------
# HBM4 — row and column maps dispatch independently
# ---------------------------------------------------------------------------

def test_hbm4_row_commands():
    enc, dec = _pair(HBM4_ROW_CA_MAP)
    cmd, args = dec.feed(enc.encode("act", pc=1, sid=2, ba=6, row=0x2A5))
    assert cmd is DRAMCommand.ACT
    assert (args["row"], args["bank"]) == (0x2A5, 6)
    assert (args["pc"], args["sid"]) == (1, 2)   # selectors pass through
    assert dec.feed(enc.encode("preab", pc=0))[0] is DRAMCommand.PREA
    assert dec.feed(enc.encode("refpb", pc=0, sid=0, ba=3))[0] \
        is DRAMCommand.REF
    assert dec.feed(enc.encode("sre"))[0] is DRAMCommand.SRE


def test_hbm4_column_commands():
    enc, dec = _pair(HBM4_COL_CA_MAP)
    cmd, args = dec.feed(enc.encode("wra", pc=0, sid=1, ba=9, col=17))
    assert cmd is DRAMCommand.WRA
    assert (args["col"], args["bank"], args["auto_precharge"]) == \
        (17, 9, True)
    cmd, args = dec.feed(enc.encode("mrs", ma=0x15, op=0x5A))
    assert cmd is DRAMCommand.MRS
    assert (args["mr_addr"], args["mr_data"]) == (0x15, 0x5A)


# ---------------------------------------------------------------------------
# LPDDR5/6 — split ACTIVATE and MRW pairs, operand-encoded AP/AB
# ---------------------------------------------------------------------------

def test_lpddr5_split_activate():
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    row = 0x2A5A5
    assert dec.feed(enc.encode("act1", ba=0b1010,
                               row_hi=(row >> 11) & 0x7F)) is None
    cmd, args = dec.feed(enc.encode("act2", row_lo=row & 0x7FF))
    assert cmd is DRAMCommand.ACT
    assert args["row"] == row
    assert args["bank"] == 0b1010      # latched from ACT-1


def test_lpddr5_intervening_commands_survive_the_pair():
    """Note 4 allows CAS/WR/RD/PRE between ACT-1 and ACT-2."""
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    assert dec.feed(enc.encode("act1", ba=3, row_hi=0x7F)) is None
    assert dec.feed(enc.encode("rd16", ba=1, col=4, ap=0))[0] \
        is DRAMCommand.RD
    cmd, args = dec.feed(enc.encode("act2", row_lo=0x123))
    assert cmd is DRAMCommand.ACT
    assert args["row"] == (0x7F << 11) | 0x123 and args["bank"] == 3


def test_lpddr5_operand_encoded_ap_and_ab():
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    cmd, args = dec.feed(enc.encode("wr16", ba=2, col=0x2A, ap=1))
    assert cmd is DRAMCommand.WRA and args["auto_precharge"] is True
    cmd, args = dec.feed(enc.encode("wr16", ba=2, col=0x2A, ap=0))
    assert cmd is DRAMCommand.WR and "auto_precharge" not in args
    cmd, args = dec.feed(enc.encode("pre", ba=2, ab=1))
    assert cmd is DRAMCommand.PREA and args["all_banks"] is True
    cmd, args = dec.feed(enc.encode("pre", ba=2, ab=0))
    assert cmd is DRAMCommand.PRE and "all_banks" not in args


def test_lpddr5_bank_group_composition():
    enc, dec = _pair(LPDDR5_CA_MAP_BG)
    _, args = dec.feed(enc.encode("pre", ba=0b10, bg=0b11, ab=0))
    assert args["bank"] == (0b11 << 2) | 0b10


def test_lpddr5_mrw_pair():
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    assert dec.feed(enc.encode("mrw1", ma=0x5A)) is None
    cmd, args = dec.feed(enc.encode("mrw2", op=0xC3))
    assert cmd is DRAMCommand.MRS
    assert (args["mr_addr"], args["mr_data"]) == (0x5A, 0xC3)


def test_lpddr6_split_activate_and_column():
    enc, dec = _pair(LPDDR6_CA_MAP)
    row = 0x1A5A
    assert dec.feed(enc.encode("act1", ba=0b01, bg=0b11, sc=0,
                               row_hi=(row >> 11) & 0x3F)) is None
    cmd, args = dec.feed(enc.encode("act2", row_lo=row & 0x7FF))
    assert cmd is DRAMCommand.ACT
    assert args["row"] == row and args["bank"] == (0b11 << 2) | 0b01

    cmd, args = dec.feed(enc.encode("rd_l", ba=0b10, bg=0b01, ws=0,
                                    col=0x2A, ap=1, sc=1))
    assert cmd is DRAMCommand.RDA
    assert args["col"] == 0x2A and args["sc"] == 1


def test_lpddr6_refresh_carries_rfm_and_dual_bank():
    enc, dec = _pair(LPDDR6_CA_MAP)
    cmd, args = dec.feed(enc.encode("ref", ba=1, bg=2, sc=0, rfm=1,
                                    dbg=0b10, ab=0))
    assert cmd is DRAMCommand.REF
    assert (args["rfm"], args["dbg"]) == (1, 0b10)
    cmd, args = dec.feed(enc.encode("ref", ba=0, bg=0, sc=0, rfm=0,
                                    dbg=0, ab=1))
    assert args["all_banks"] is True


# ---------------------------------------------------------------------------
# Orphan halves: strict raises, monitors drop
# ---------------------------------------------------------------------------

def test_orphan_second_half_raises_in_strict_mode():
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    with pytest.raises(ValueError, match="no preceding"):
        dec.feed(enc.encode("act2", row_lo=0))


def test_orphan_second_half_dropped_when_not_strict():
    enc, dec = _pair(LPDDR6_CA_MAP, strict=False)
    assert dec.feed(enc.encode("act2", row_lo=0x7FF)) is None
    # ...and the decoder stays usable afterwards.
    assert dec.feed(enc.encode("act1", ba=0, bg=0, sc=0,
                               row_hi=1)) is None
    assert dec.feed(enc.encode("act2", row_lo=2))[0] is DRAMCommand.ACT


def test_reset_drops_latched_half():
    enc, dec = _pair(LPDDR5_CA_MAP_16B)
    dec.feed(enc.encode("act1", ba=1, row_hi=0x7F))
    dec.reset()
    with pytest.raises(ValueError):
        dec.feed(enc.encode("act2", row_lo=0))


def test_unknown_map_needs_a_translation_table():
    from CocoTBFramework.components.dfi.ca_map import (
        CAMap,
        CommandSpec,
        OpcodeBit,
    )
    m = CAMap("vendor_z", 4, (CommandSpec("nop", 1, (OpcodeBit(0, 0, 1),)),))
    with pytest.raises(KeyError, match="no translation table"):
        CACommandDecoder(m)
    # ...but an explicit table works.
    dec = CACommandDecoder(m, translations={})
    assert dec.feed([1])[0] is DRAMCommand.NOP


def test_every_shipped_map_has_a_translation():
    for name in ("ddr5", "hbm4_row", "hbm4_col", "lpddr5_bg",
                 "lpddr5_16b", "lpddr5_8b", "lpddr6"):
        assert name in TRANSLATIONS


@pytest.mark.parametrize("camap", [
    DDR5_CA_MAP, HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP,
    LPDDR5_CA_MAP_16B, LPDDR5_CA_MAP_BG, LPDDR6_CA_MAP,
])
def test_translations_name_real_commands(camap):
    """Every translated name must exist in its map — catches drift."""
    known = {c.name for c in camap.commands}
    for name, tr in TRANSLATIONS[camap.name].items():
        assert name in known, f"{camap.name}: {name} not in map"
        if tr.pairs_with:
            assert tr.pairs_with in known
