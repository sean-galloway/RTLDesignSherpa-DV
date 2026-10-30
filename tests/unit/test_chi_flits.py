"""CHI flit layouts: field positions against Tables B13.6 to B13.9, exact
pack/unpack round trips, and the aliasing of shared bits."""
from __future__ import annotations

import random

import pytest

from CocoTBFramework.components.chi import (
    CHANNELS,
    CHIConfig,
    CHIDatFlit,
    CHIReqFlit,
    CHIRspFlit,
    CHISnpFlit,
    DatOpcode,
    ReqOpcode,
    RspOpcode,
    Size,
    SnpOpcode,
    flit_class,
)


def positions(flit):
    fc = flit.field_config
    return {n: fc.get_field(n).bit_position for n in fc.field_names()}


def test_req_positions_table_b13_6_default_widths():
    # Walk Table B13.6 from bit 0 at NodeID 7, RAW 44, no optional buses.
    p = positions(CHIReqFlit(CHIConfig()))
    assert p['qos'] == (3, 0)
    assert p['tgtid'] == (10, 4)
    assert p['srcid'] == (17, 11)
    assert p['txnid'] == (29, 18)
    assert p['returnnid'] == (36, 30)
    assert p['stashnidvalid'] == (37, 37)
    assert p['returntxnid'] == (49, 38)
    assert p['opcode'] == (56, 50)
    assert p['multireq'] == (57, 57)
    assert p['size'] == (60, 58)            # {3'b0, Size}: Size is the low 3 of the 6
    assert p['numreq_hi'] == (63, 61)
    assert p['addr'] == (107, 64)
    assert p['pas'] == (110, 108)
    assert p['likelyshared'] == (111, 111)
    assert p['allowretry'] == (112, 112)
    assert p['order'] == (114, 113)
    assert p['pcrdtype'] == (118, 115)
    assert p['memattr'] == (122, 119)
    assert p['snpattr'] == (123, 123)
    assert p['lpid'] == (131, 124)
    assert p['excl'] == (132, 132)
    assert p['expcompack'] == (133, 133)
    assert p['tagop'] == (135, 134)
    assert p['tracetag'] == (136, 136)
    assert 'mpam' not in p and 'rsvdc' not in p


def test_rsp_positions_table_b13_7():
    p = positions(CHIRspFlit(CHIConfig(nodeid_width=16)))
    assert p['txnid'] == (47, 36)
    assert p['opcode'] == (52, 48)
    assert p['resperr'] == (54, 53)
    assert p['resp'] == (57, 55)
    assert p['fwdstate'] == (60, 58)
    assert p['cbusy'] == (63, 61)
    assert p['dbid'] == (75, 64)
    assert p['pcrdtype'] == (79, 76)
    assert p['cachelineid'] == (88, 83)


def test_snp_positions_table_b13_8():
    p = positions(CHISnpFlit(CHIConfig(addr_width=44)))
    assert p['srcid'] == (10, 4)
    assert p['txnid'] == (22, 11)
    assert p['fwdnid'] == (29, 23)
    assert p['fwdtxnid'] == (41, 30)
    assert p['opcode'] == (46, 42)
    assert p['addr'] == (87, 47)            # SAW = 41
    assert p['pas'] == (90, 88)
    assert p['tracetag'] == (93, 93)


def test_dat_positions_table_b13_9_128():
    p = positions(CHIDatFlit(CHIConfig(data_width=128)))
    assert p['homenid'] == (36, 30)
    assert p['opcode'] == (40, 37)
    assert p['resperr'] == (42, 41)
    assert p['resp'] == (45, 43)
    assert p['datasource'] == (53, 46)
    assert p['datapull'] == (54, 54)
    assert p['cbusy'] == (57, 55)
    assert p['dbid'] == (73, 58)            # {4'b0, DBID[11:0]} is 16 bits
    assert p['ccid'] == (75, 74)
    assert p['dataid'] == (77, 76)
    assert p['cachelineid'] == (83, 78)
    assert p['tagop'] == (85, 84)
    assert p['tag'] == (89, 86)             # DW/32 = 4
    assert p['tu'] == (90, 90)              # DW/128 = 1
    assert p['be'] == (111, 96)             # DW/8 = 16
    assert p['data'] == (239, 112)
    assert 'datacheck' not in p and 'poison' not in p


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("kw", [dict(), dict(nodeid_width=16, addr_width=52, data_width=512,
                                             req_rsvdc_width=32, dat_rsvdc_width=16, mpam_width=12,
                                             pbha_width=4, mecid_width=16, data_check=True, poison=True)])
def test_pack_unpack_round_trip_random(channel, kw):
    cfg = CHIConfig(**kw).validate()
    cls = flit_class(channel)
    rng = random.Random(7)
    for _ in range(20):
        f = cls(cfg)
        for name in f.field_config.field_names():
            f.fields[name] = rng.getrandbits(f.field_config.get_field(name).bits)
        word = f.pack()
        assert word < (1 << cfg.flit_width(channel))
        g = cls.from_word(cfg, word)
        assert g == f and g.pack() == word


def test_pack_puts_each_field_where_its_table_row_says():
    cfg = CHIConfig()
    f = CHIReqFlit(cfg, opcode=ReqOpcode.ReadShared, txnid=0xABC, addr=0x1234_5678, size=Size.B64)
    w = f.pack()
    assert (w >> 18) & 0xFFF == 0xABC
    assert (w >> 50) & 0x7F == ReqOpcode.ReadShared
    assert (w >> 58) & 0x7 == Size.B64
    assert (w >> 64) & ((1 << 44) - 1) == 0x1234_5678


def test_aliases_read_and_write_the_shared_slot():
    f = CHIReqFlit(CHIConfig(), stashnid=5, cah=1, pgroupid=0x3C)
    assert f.returnnid == 5 and f.excl == 1 and f.lpid == 0x3C
    assert f.datatarget == 5
    f.taggroupid = 0x11
    assert f.lpid == 0x11
    r = CHIRspFlit(CHIConfig(), taggroupid=0x55)
    assert r.dbid == 0x55
    # sub-fields of a wider slot are deliberately NOT aliased
    with pytest.raises(AttributeError):
        _ = CHIRspFlit(CHIConfig()).datapull
    with pytest.raises(AttributeError):
        _ = CHIDatFlit(CHIConfig()).fwdstate


def test_lcrd_return_is_opcode_zero_on_every_channel():
    cfg = CHIConfig()
    for cls, op in ((CHIReqFlit, ReqOpcode.ReqLCrdReturn), (CHIRspFlit, RspOpcode.RespLCrdReturn),
                    (CHISnpFlit, SnpOpcode.SnpLCrdReturn), (CHIDatFlit, DatOpcode.DataLCrdReturn)):
        assert int(op) == 0
        assert cls(cfg, opcode=op).is_lcrd_return
        assert not cls(cfg, opcode=1).is_lcrd_return


def test_data_bytes_little_endian_and_snp_byte_addr():
    cfg = CHIConfig(data_width=128)
    d = CHIDatFlit(cfg).set_data_bytes(bytes(range(16)))
    assert d.data == 0x0F0E0D0C0B0A09080706050403020100
    assert d.data_bytes() == bytes(range(16))
    s = CHISnpFlit(cfg, addr=0x1000 >> 3)
    assert s.byte_addr == 0x1000


def test_str_names_the_opcode():
    assert 'ReadShared' in str(CHIReqFlit(CHIConfig(), opcode=ReqOpcode.ReadShared))
    assert 'CompData' in repr(CHIDatFlit(CHIConfig(), opcode=DatOpcode.CompData))
