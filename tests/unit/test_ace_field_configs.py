# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for ACE field configurations."""

import pytest

from CocoTBFramework.components.ace.ace_field_configs import AXI4ACEFieldConfigHelper


@pytest.mark.parametrize("user_width", [0, 1, 4])
def test_ar_config_appends_arsnoop_after_user(user_width):
    cfg = AXI4ACEFieldConfigHelper.create_ar_field_config(user_width=user_width)
    names = list(cfg.field_names())
    assert "snoop" in names
    # Default MSB-first ordering: last-added field is first in field_names().
    # ARSNOOP, ARDOMAIN, ARBAR are appended in that order (IHI 0022H D2.1.1).
    assert names[:3] == ["bar", "domain", "snoop"]
    snoop = cfg.get_field("snoop")
    assert snoop.bits == 4
    assert snoop.default == 0
    assert cfg.get_field("domain").bits == 2
    assert cfg.get_field("bar").bits == 2


@pytest.mark.parametrize("user_width", [0, 1, 4])
def test_aw_config_appends_awsnoop_after_user(user_width):
    cfg = AXI4ACEFieldConfigHelper.create_aw_field_config(user_width=user_width)
    names = list(cfg.field_names())
    assert "snoop" in names
    # AWSNOOP, AWDOMAIN, AWBAR are appended in that order (IHI 0022H D2.1.2).
    assert names[:3] == ["bar", "domain", "snoop"]
    snoop = cfg.get_field("snoop")
    assert snoop.bits == 3
    assert snoop.default == 0
    assert cfg.get_field("domain").bits == 2
    assert cfg.get_field("bar").bits == 2


def test_ac_field_config():
    cfg = AXI4ACEFieldConfigHelper.create_ac_field_config(addr_width=64)
    names = list(cfg.field_names())
    # Default MSB-first ordering: last-added prot is first, addr is last.
    assert names == ["prot", "snoop", "addr"]
    assert cfg.get_field("addr").bits == 64
    assert cfg.get_field("snoop").bits == 4
    assert cfg.get_field("prot").bits == 3


def test_cr_field_config():
    cfg = AXI4ACEFieldConfigHelper.create_cr_field_config()
    names = list(cfg.field_names())
    assert names == ["resp"]
    assert cfg.get_field("resp").bits == 5


def test_cd_field_config():
    cfg = AXI4ACEFieldConfigHelper.create_cd_field_config(data_width=128)
    names = list(cfg.field_names())
    # Default MSB-first ordering: last-added last is first.
    assert names == ["last", "data"]
    assert cfg.get_field("data").bits == 128
    assert cfg.get_field("last").bits == 1


def test_create_all_field_configs_includes_ace_channels():
    cfgs = AXI4ACEFieldConfigHelper.create_all_field_configs()
    assert set(cfgs.keys()) == {"AW", "W", "B", "AR", "R", "AC", "CR", "CD"}


def test_ar_aw_snoop_field_packing_order_matches_rtl():
    """The ACE address fields are the last ones added (snoop, domain, bar), so
    in default MSB-first mode bar sits at the top of the packed payload with
    domain and snoop directly below, the order ``rtl/amba/ace`` appends them.
    """
    for cfg in (AXI4ACEFieldConfigHelper.create_ar_field_config(),
                AXI4ACEFieldConfigHelper.create_aw_field_config()):
        top = cfg.get_total_bits() - 1
        assert cfg.get_field("bar").bit_position[0] == top
        assert cfg.get_field("domain").bit_position[0] == top - 2
        assert cfg.get_field("snoop").bit_position[0] == top - 4


def test_r_config_carries_four_bit_rresp():
    """ACE RRESP is 4 bits: [1:0] response, [2] PassDirty, [3] IsShared
    (IHI 0022H D2.1.3, Table D3-14). The AXI4 R config has 2."""
    cfg = AXI4ACEFieldConfigHelper.create_r_field_config()
    assert cfg.get_field("resp").bits == 4
    assert AXI4ACEFieldConfigHelper.create_all_field_configs(channels=["R"])["R"].get_field("resp").bits == 4
