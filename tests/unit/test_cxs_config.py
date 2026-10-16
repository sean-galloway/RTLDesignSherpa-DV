"""CXS properties: per-issue legality and the CXSCNTL layout.

The width table is transcribed from IHI 0079D Table 4-5 (16-byte start
alignment) and Table 4-7 (4-byte), every row, with the END field's LSB as a
second golden column so a layout that gets the total right by accident still
fails.
"""
from __future__ import annotations

import pytest

from CocoTBFramework.components.cxs import CONFIG_RULES, CXSConfig, CXSIssue, chk_width

# (N, W, align) -> (CXSCNTLWIDTH, END lsb)
TABLE_4_5_AND_4_7 = {
    (2, 256, 16): (14, 4), (2, 512, 16): (18, 6), (2, 1024, 16): (22, 8), (2, 2048, 16): (26, 10),
    (3, 512, 16): (27, 9), (3, 1024, 16): (33, 12), (3, 2048, 16): (39, 15),
    (4, 512, 16): (36, 12), (4, 1024, 16): (44, 16), (4, 2048, 16): (52, 20),
    (2, 256, 4): (18, 8), (2, 512, 4): (22, 10), (2, 1024, 4): (26, 12), (2, 2048, 4): (30, 14),
    (3, 256, 4): (27, 12), (3, 512, 4): (33, 15), (3, 1024, 4): (39, 18), (3, 2048, 4): (45, 21),
    (4, 256, 4): (36, 16), (4, 512, 4): (44, 20), (4, 1024, 4): (52, 24), (4, 2048, 4): (60, 28),
}


@pytest.mark.parametrize("key", sorted(TABLE_4_5_AND_4_7))
def test_cntl_width_matches_spec_tables(key):
    n, w, align = key
    cfg = CXSConfig(issue='D', data_width=w, max_pkt_per_flit=n, start_align=align).validate()
    width, end_lsb = TABLE_4_5_AND_4_7[key]
    assert cfg.cntl_width == width
    assert cfg.end_lsb == end_lsb
    rows = cfg.cntl_fields()
    assert rows[-1][1] + rows[-1][2] == width          # fields tile the word
    assert sum(r[2] for r in rows) == width


def test_table_4_2_example_bit_positions():
    # Table 4-2 (Issue B), 2 packets per 256-bit flit: the exact placement
    cfg = CXSConfig(issue='B', data_width=256, max_pkt_per_flit=2)
    assert cfg.cntl_fields() == [
        ("START", 0, 2), ("START0PTR", 2, 1), ("START1PTR", 3, 1),
        ("END", 4, 2), ("ENDERROR", 6, 2), ("END0PTR", 8, 3), ("END1PTR", 11, 3)]


def test_lite_has_no_cntl():
    cfg = CXSConfig.lite(data_width=72, issue='C').validate()
    assert cfg.is_lite and cfg.cntl_width == 0 and cfg.cntl_fields() == []


def test_issue_coercion():
    assert CXSConfig(issue='b').issue is CXSIssue.B
    assert CXSConfig(issue=3).issue is CXSIssue.C


LEGAL = [
    dict(issue='A', data_width=256, max_pkt_per_flit=2, max_credit=15),
    dict(issue='A', data_width=1024, max_pkt_per_flit=4),
    dict(issue='B', data_width=512, max_pkt_per_flit=3, has_last=True, has_prcltype=True),
    dict(issue='C', data_width=8, max_pkt_per_flit=1, max_credit=63),
    dict(issue='C', data_width=2048, max_pkt_per_flit=1),
    dict(issue='D', data_width=2048, max_pkt_per_flit=4),
    dict(issue='D', data_width=256, max_pkt_per_flit=4, start_align=4),
    dict(issue='D', data_width=512, srcid_width=8, tgtid_width=8, user_width=128),
]

ILLEGAL = [  # (props, rule)
    (dict(issue='A', max_pkt_per_flit=1, data_width=256), 3),
    (dict(issue='C', max_pkt_per_flit=1, data_width=12), 4),
    (dict(issue='D', max_pkt_per_flit=1, has_last=True), 5),
    (dict(issue='C', data_width=2048, max_pkt_per_flit=2), 6),
    (dict(issue='D', data_width=128, max_pkt_per_flit=2), 6),
    (dict(issue='D', data_width=256, max_pkt_per_flit=3), 7),
    (dict(issue='D', start_align=8), 8),
    (dict(issue='C', start_align=4), 9),
    (dict(issue='A', has_last=True), 10),
    (dict(issue='A', has_prcltype=True), 10),
    (dict(issue='D', max_credit=0), 11),
    (dict(issue='B', max_credit=16), 12),
    (dict(issue='D', max_credit=64), 12),
    (dict(issue='D', srcid_width=9), 13),
    (dict(issue='C', user_width=4), 14),
]


@pytest.mark.parametrize("props", LEGAL)
def test_legal_property_sets(props):
    assert CXSConfig(**props).config_error() == 0


@pytest.mark.parametrize("props,rule", ILLEGAL)
def test_illegal_property_sets_name_their_rule(props, rule):
    cfg = CXSConfig(**props)
    assert cfg.config_error() == rule
    with pytest.raises(ValueError, match=f"rule {rule}"):
        cfg.validate()
    assert rule in CONFIG_RULES


def test_check_widths_table_3_2():
    cfg = CXSConfig(issue='D', data_width=512, max_pkt_per_flit=3, has_last=True,
                    has_prcltype=True, srcid_width=4, tgtid_width=2, user_width=12, check=True)
    w = cfg.check_widths()
    assert w['data'] == 64 and w['cntl'] == chk_width(27) == 4
    assert w['prcltype'] == w['srcid'] == w['tgtid'] == w['last'] == 1
    assert w['user'] == 2 and w['crdrtn'] == w['activereq'] == w['activeack'] == 1
    assert 'deacthint' not in w
    assert CXSConfig(check=False).check_widths() == {}


def test_compatibility_table_2_3():
    tx = CXSConfig(issue='D', data_width=512, max_pkt_per_flit=2, max_credit=15)
    assert tx.is_compatible_rx(tx) == []
    assert tx.is_compatible_rx(tx.with_(max_pkt_per_flit=4)) == []      # TX <= RX
    assert tx.with_(max_pkt_per_flit=4).is_compatible_rx(tx)             # TX > RX
    assert tx.is_compatible_rx(tx.with_(data_width=1024))
    assert tx.is_compatible_rx(tx.with_(max_credit=31))                  # TX < RX
    assert tx.is_compatible_rx(tx.with_(has_last=True))


def test_rtl_parameters_round_trip():
    cfg = CXSConfig(issue='B', data_width=512, has_last=True, check=True)
    p = cfg.rtl_parameters()
    assert p['CXS_ISSUE'] == 2 and p['CXS_HAS_LAST'] == 1 and p['CXS_CHECK'] == 1
    assert p['CXS_HAS_PRCLTYPE'] == 0 and p['CXS_LINK_CTRL'] == 1


def test_credit_beyond_spec_skips_rule_12_only():
    wide = CXSConfig(issue='D', data_width=512, max_pkt_per_flit=2, max_credit=512)
    assert wide.config_error() == 12
    ok = wide.with_(credit_beyond_spec=True)
    assert ok.config_error() == 0
    assert ok.rtl_parameters()['CXS_CREDIT_BEYOND_SPEC'] == 1
    # every other rule still applies
    assert ok.with_(max_credit=0).config_error() == 11
    assert ok.with_(data_width=128).config_error() == 6
