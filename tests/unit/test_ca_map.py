"""Declarative CA maps: engine semantics, and the HBM4 reference maps
differentially tested against the hand-written hbm4_commands codecs."""

import json

import pytest

from CocoTBFramework.components.dfi import hbm4_commands as hc
from CocoTBFramework.components.dfi.ca_map import (
    HBM4_COL_CA_MAP,
    HBM4_ROW_CA_MAP,
    BitRun,
    CACodec,
    CAMap,
    CommandSpec,
    FieldSpec,
    OpcodeBit,
    camap_from_dict,
)

ROW = CACodec(HBM4_ROW_CA_MAP)
COL = CACodec(HBM4_COL_CA_MAP)


# ---------------------------------------------------------------------------
# Differential: map-driven engine == hand-written JESD270-4A codecs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pc,sid,ba,row", [
    (0, 0, 0, 0), (1, 3, 15, 0x7FFF), (1, 2, 10, 0x5A5A), (0, 1, 6, 0x2AA5),
])
def test_act_matches_handwritten(pc, sid, ba, row):
    assert ROW.encode("act", pc=pc, sid=sid, ba=ba, row=row) == \
        hc.encode_row_act(pc=pc, sid=sid, ba=ba, row=row)


def test_single_edge_rows_match_handwritten():
    assert ROW.encode("rnop") == hc.encode_row_nop()
    assert ROW.encode("prepb", pc=1, sid=3, ba=15) == \
        hc.encode_row_prepb(1, 3, 15)
    assert ROW.encode("preab", pc=1) == hc.encode_row_preab(1)
    assert ROW.encode("refpb", pc=0, sid=1, ba=9) == \
        hc.encode_row_refpb(0, 1, 9)
    assert ROW.encode("refab", pc=1) == hc.encode_row_refab(1)
    assert ROW.encode("rfmpb", pc=1, sid=0, ba=3) == \
        hc.encode_row_rfmpb(1, 0, 3)
    assert ROW.encode("rfmab", pc=0) == hc.encode_row_rfmab(0)
    assert ROW.encode("pde") == hc.encode_row_pde()
    assert ROW.encode("sre") == hc.encode_row_sre()


@pytest.mark.parametrize("kwargs", [
    dict(pc=0, sid=0, ba=0, col=0),
    dict(pc=1, sid=3, ba=15, col=31),
    dict(pc=1, sid=2, ba=9, col=17),
])
def test_col_rd_wr_match_handwritten(kwargs):
    assert list(COL.encode("rd", **kwargs)) == \
        list(hc.encode_col_rd(**kwargs))
    assert list(COL.encode("rda", **kwargs)) == \
        list(hc.encode_col_rd(auto_precharge=True, **kwargs))
    assert list(COL.encode("wr", **kwargs)) == \
        list(hc.encode_col_wr(**kwargs))
    assert list(COL.encode("wra", **kwargs)) == \
        list(hc.encode_col_wr(auto_precharge=True, **kwargs))


@pytest.mark.parametrize("ma,op", [(0, 0), (0x1F, 0xFF), (0x15, 0x5A)])
def test_mrs_matches_handwritten(ma, op):
    assert list(COL.encode("mrs", ma=ma, op=op)) == \
        list(hc.encode_col_mrs(ma=ma, op=op))


# ---------------------------------------------------------------------------
# Engine decode
# ---------------------------------------------------------------------------

def test_row_decode_roundtrip():
    edges = ROW.encode("act", pc=1, sid=1, ba=6, row=0x1234)
    name, fields = ROW.decode(edges)
    assert name == "act"
    assert fields == {"pc": 1, "sid": 1, "ba": 6, "row": 0x1234}


def test_streaming_match_gives_edge_count():
    spec = ROW.match(ROW.encode("act", pc=0, sid=0, ba=0, row=0)[0])
    assert spec.name == "act" and spec.n_edges == 3
    spec = ROW.match(ROW.encode("preab", pc=0)[0])
    assert spec.name == "preab" and spec.n_edges == 1


def test_alias_decodes_to_primary():
    # RNOP and PDX/SRX share the all-high pattern; decode yields rnop.
    name, _ = ROW.decode(ROW.encode("pdx_srx"))
    assert name == "rnop"


def test_col_decode_roundtrip():
    name, f = COL.decode(list(COL.encode("wra", pc=1, sid=2, ba=11, col=19)))
    assert name == "wra"
    assert f == {"pc": 1, "sid": 2, "ba": 11, "col": 19}
    name, f = COL.decode(list(COL.encode("mrs", ma=0x11, op=0xC3)))
    assert (name, f["ma"], f["op"]) == ("mrs", 0x11, 0xC3)


def test_encode_rejects_unknown_and_oversize_fields():
    with pytest.raises(ValueError):
        ROW.encode("preab", pc=0, bogus=1)
    with pytest.raises(ValueError):
        ROW.encode("act", pc=0, sid=0, ba=0, row=1 << 15)


# ---------------------------------------------------------------------------
# Custom device maps: dict/JSON loading + validation
# ---------------------------------------------------------------------------

def test_camap_from_dict_roundtrip():
    d = {
        "name": "vendor_x_row", "bus_width": 6,
        "commands": [
            {"name": "nop", "n_edges": 1, "opcode": [[0, 0, 1], [0, 1, 1]]},
            {"name": "act", "n_edges": 2,
             "opcode": [[0, 0, 0], [0, 1, 1]],
             "fields": [{"name": "row", "width": 8,
                         "runs": [[0, 2, 0, 4], [1, 2, 4, 4]]}]},
        ],
    }
    codec = CACodec(camap_from_dict(json.loads(json.dumps(d))))
    edges = codec.encode("act", row=0xA5)
    name, f = codec.decode(edges)
    assert (name, f["row"]) == ("act", 0xA5)


def test_map_validation_rejects_ambiguity():
    with pytest.raises(ValueError, match="not distinguishable"):
        CAMap("bad", 4, (
            CommandSpec("a", 1, (OpcodeBit(0, 0, 1),)),
            CommandSpec("b", 1, (OpcodeBit(0, 1, 1),)),  # overlaps 'a'
        ))


def test_map_validation_rejects_bad_field_width():
    with pytest.raises(ValueError, match="declared width"):
        FieldSpec("f", 4, (BitRun(0, 0, 0, 3),))


# ---------------------------------------------------------------------------
# Multi-edge opcode signatures (DDR5 WR/WRA-style later-edge splits)
# ---------------------------------------------------------------------------

def _later_edge_map():
    return CAMap("split", 4, (
        CommandSpec("wr", 2, (OpcodeBit(0, 0, 1), OpcodeBit(1, 3, 1)),
                    fields=(FieldSpec("c", 2, (BitRun(1, 0, 0, 2),)),)),
        CommandSpec("wra", 2, (OpcodeBit(0, 0, 1), OpcodeBit(1, 3, 0)),
                    fields=(FieldSpec("c", 2, (BitRun(1, 0, 0, 2),)),)),
    ))


def test_later_edge_split_validates_and_decodes():
    codec = CACodec(_later_edge_map())
    for name in ("wr", "wra"):
        got, f = codec.decode(codec.encode(name, c=2))
        assert (got, f["c"]) == (name, 2)
    # match() on the shared first edge still gives the edge count.
    assert codec.match(codec.encode("wra", c=0)[0]).n_edges == 2


def test_later_edge_split_requires_equal_edge_counts():
    with pytest.raises(ValueError, match="different edge counts"):
        CAMap("bad", 4, (
            CommandSpec("a", 1, (OpcodeBit(0, 0, 1),)),
            CommandSpec("b", 2, (OpcodeBit(0, 0, 1), OpcodeBit(1, 3, 0))),
        ))
