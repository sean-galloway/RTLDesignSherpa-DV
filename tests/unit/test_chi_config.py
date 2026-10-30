"""CHI configuration: parameter legality (B16.1) and the flit widths of
Tables B13.6 to B13.9, checked against the totals the tables print."""
from __future__ import annotations

import pytest

from CocoTBFramework.components.chi import CONFIG_RULES, CHIConfig, CHIIssue, NodeType

# Table totals, transcribed: (nodeid_width, addr_width, data_width, extras) -> widths
# Table B13.6: REQ = 93 + RAW ... to 120 + RAW (NodeID 7 -> 16), + Y + M + PB + S + Max(E, R)
# Table B13.7: RSP = 71 to 89
# Table B13.8: SNP = 53 + SAW to 71 + SAW, + M + E
# Table B13.9: DAT = 240..267 / 389..416 / 687..714 + Y + DC + P
MIN_MAX = [
    (dict(nodeid_width=7, addr_width=44, data_width=128), dict(req=137, rsp=71, snp=94, dat=240)),
    (dict(nodeid_width=16, addr_width=44, data_width=128), dict(req=164, rsp=89, snp=112, dat=267)),
    (dict(nodeid_width=7, addr_width=52, data_width=256), dict(req=145, rsp=71, snp=102, dat=389)),
    (dict(nodeid_width=16, addr_width=52, data_width=512), dict(req=172, rsp=89, snp=120, dat=714)),
]


@pytest.mark.parametrize("kw,expect", MIN_MAX)
def test_flit_widths_match_table_totals(kw, expect):
    cfg = CHIConfig(**kw).validate()
    assert {c: cfg.flit_width(c) for c in expect} == expect


def test_optional_buses_add_their_widths():
    base = CHIConfig(nodeid_width=7, addr_width=44, data_width=512).validate()
    full = base.with_(req_rsvdc_width=32, dat_rsvdc_width=24, mpam_width=15, pbha_width=4,
                      mecid_width=16, streamid_width=16, secsid1_width=1,
                      data_check=True, poison=True).validate()
    # REQ: + Y + M + PB + S + Max(E, R)
    assert full.req_flit_width == base.req_flit_width + 32 + 15 + 4 + 1 + 16
    # SNP: + M + E
    assert full.snp_flit_width == base.snp_flit_width + 15 + 16
    # DAT: + Y + DC (DW/8) + P (DW/64) + E
    assert full.dat_flit_width == base.dat_flit_width + 24 + 64 + 8 + 16
    assert full.rsp_flit_width == base.rsp_flit_width


def test_snp_addr_is_three_less_than_req_addr():
    cfg = CHIConfig(addr_width=48)
    assert cfg.snp_addr_width == 45


@pytest.mark.parametrize("kw,rule", [
    (dict(issue='G'), 1), (dict(nodeid_width=6), 2), (dict(nodeid_width=17), 2),
    (dict(addr_width=43), 3), (dict(addr_width=53), 3), (dict(data_width=64), 4),
    (dict(req_rsvdc_width=5), 5), (dict(dat_rsvdc_width=20), 6), (dict(mpam_width=8), 7),
    (dict(pbha_width=2), 8), (dict(mecid_width=8), 9), (dict(streamid_width=8), 10),
    (dict(secsid1_width=2), 11), (dict(max_lcredit=0), 12), (dict(max_lcredit=16), 12),
])
def test_illegal_sets_name_their_rule(kw, rule):
    cfg = CHIConfig(**kw)
    assert cfg.config_error() == rule
    with pytest.raises(ValueError, match=f"rule {rule}:"):
        cfg.validate()
    assert rule in CONFIG_RULES


def test_legal_defaults_and_coercion():
    assert CHIConfig().config_error() == 0
    assert CHIConfig(issue='h').issue is CHIIssue.H
    assert CHIConfig(node_type='hn_f').node_type is NodeType.HN_F
    assert CHIConfig(node_type='RN-I').node_type is NodeType.RN_I


def test_channel_presence_per_node_type():
    rnf = CHIConfig(node_type='RN-F')
    assert rnf.tx_channels == ('req', 'rsp', 'dat') and rnf.rx_channels == ('rsp', 'dat', 'snp')
    rni = CHIConfig(node_type='RN-I')
    assert 'snp' not in rni.rx_channels and not rni.has_snp
    hnf = CHIConfig(node_type='HN-F')
    assert hnf.tx_channels == ('rsp', 'dat', 'snp') and hnf.rx_channels == ('req', 'rsp', 'dat')
    snf = CHIConfig(node_type='SN-F')
    assert snf.tx_channels == ('rsp', 'dat') and snf.rx_channels == ('req', 'dat')


def test_rtl_parameters_carry_the_widths():
    p = CHIConfig(data_width=256).rtl_parameters()
    assert p['DAT_FLIT_WIDTH'] == 389 and p['DATA_WIDTH'] == 256 and p['MAX_LCREDIT'] == 15
