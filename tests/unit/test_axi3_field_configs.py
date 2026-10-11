# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for AXI3 field configuration helpers."""

import pytest

from CocoTBFramework.components.axi3.axi3_field_configs import AXI3FieldConfigHelper


def test_aw_len_is_four_bits():
    cfg = AXI3FieldConfigHelper.create_aw_field_config()
    assert cfg.get_field('len').bits == 4


def test_ar_len_is_four_bits():
    cfg = AXI3FieldConfigHelper.create_ar_field_config()
    assert cfg.get_field('len').bits == 4


def test_aw_lock_is_two_bits():
    cfg = AXI3FieldConfigHelper.create_aw_field_config()
    assert cfg.get_field('lock').bits == 2


def test_ar_lock_is_two_bits():
    cfg = AXI3FieldConfigHelper.create_ar_field_config()
    assert cfg.get_field('lock').bits == 2


def test_aw_has_no_qos_or_region():
    cfg = AXI3FieldConfigHelper.create_aw_field_config()
    names = set(cfg.field_names())
    assert 'qos' not in names
    assert 'region' not in names


def test_ar_has_no_qos_or_region():
    cfg = AXI3FieldConfigHelper.create_ar_field_config()
    names = set(cfg.field_names())
    assert 'qos' not in names
    assert 'region' not in names


def test_w_has_id_field():
    cfg = AXI3FieldConfigHelper.create_w_field_config()
    names = set(cfg.field_names())
    assert 'id' in names
    assert cfg.get_field('id').bits == 8


def test_w_id_width_follows_argument():
    cfg = AXI3FieldConfigHelper.create_w_field_config(id_width=4)
    assert cfg.get_field('id').bits == 4


def test_create_all_field_configs_includes_all_channels():
    cfgs = AXI3FieldConfigHelper.create_all_field_configs()
    assert set(cfgs.keys()) == {'AW', 'W', 'B', 'AR', 'R'}


def test_user_width_zero_removes_user_field():
    cfg = AXI3FieldConfigHelper.create_aw_field_config(user_width=0)
    assert 'user' not in set(cfg.field_names())


def test_user_width_non_zero_adds_user_field():
    cfg = AXI3FieldConfigHelper.create_aw_field_config(user_width=4)
    assert cfg.get_field('user').bits == 4


@pytest.mark.parametrize("id_width,addr_width,data_width,user_width,valid", [
    (8, 32, 32, 1, True),
    (0, 32, 32, 1, False),   # id_width too small
    (8, 32, 33, 1, False),   # data_width not in allowed set
    (8, 32, 32, 33, False),  # user_width too large
])
def test_validate_axi3_widths(id_width, addr_width, data_width, user_width, valid):
    ok, errors = AXI3FieldConfigHelper.validate_axi3_widths(id_width, addr_width, data_width, user_width)
    assert ok is valid
    if valid:
        assert not errors
    else:
        assert errors


def test_get_axi3_field_configs_returns_requested_channels():
    from CocoTBFramework.components.axi3.axi3_field_configs import get_axi3_field_configs
    cfgs = get_axi3_field_configs(channels=['AW', 'AR'])
    assert set(cfgs.keys()) == {'AW', 'AR'}
