"""Unit tests for shared/field_config.py."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.field_config import (
    FieldConfig,
    FieldDefinition,
)


def test_field_definition_validates_positive_bit_width():
    with pytest.raises(ValueError, match="must have positive bit width"):
        FieldDefinition(name="bad", bits=0)


def test_field_definition_validates_active_bits_range():
    with pytest.raises(ValueError, match="Invalid active_bits"):
        FieldDefinition(name="oob", bits=4, active_bits=(7, 0))  # msb >= bits


def test_field_definition_defaults_active_bits_to_full_width():
    fd = FieldDefinition(name="data", bits=8)
    assert fd.active_bits == (7, 0)


def test_field_definition_defaults_description_from_name():
    fd = FieldDefinition(name="pwrite_enable", bits=1)
    assert fd.description == "Pwrite enable"


def test_field_config_add_field_returns_self_for_chaining():
    cfg = FieldConfig()
    result = cfg.add_field(FieldDefinition(name="a", bits=4))
    assert result is cfg


def test_create_data_only_produces_single_field():
    cfg = FieldConfig.create_data_only(data_width=32)
    field_names = list(cfg.field_names())
    assert "data" in field_names
    assert len(field_names) == 1


def test_validate_and_create_from_dict():
    field_dict = {
        "addr": {"bits": 12, "default": 0, "format": "hex"},
        "data": {"bits": 32, "default": 0, "format": "hex"},
    }
    cfg = FieldConfig.validate_and_create(field_dict)
    assert "addr" in cfg.field_names()
    assert "data" in cfg.field_names()


def test_fields_get_distinct_bit_positions():
    """Two non-overlapping fields should occupy distinct bit ranges."""
    cfg = FieldConfig()
    cfg.add_field(FieldDefinition(name="a", bits=4))
    cfg.add_field(FieldDefinition(name="b", bits=4))
    a_pos = cfg.get_field("a").bit_position
    b_pos = cfg.get_field("b").bit_position
    # Each is a (msb, lsb) tuple; their bit ranges must not overlap
    a_msb, a_lsb = a_pos
    b_msb, b_lsb = b_pos
    overlaps = not (a_msb < b_lsb or b_msb < a_lsb)
    assert not overlaps, f"Fields overlap: a={a_pos}, b={b_pos}"


def test_default_mode_bit_positions_pinned():
    """Pin the default-mode packing semantics: LAST field added gets highest bits.

    These exact positions are documented in field_config.py and
    docs/components/shared/components_shared_field_config.md; if this test
    fails, the packing behavior changed and every existing packet layout in
    the field breaks. Do not 'fix' this test - fix the regression.
    """
    cfg = FieldConfig()
    cfg.add_field(FieldDefinition(name="a", bits=4))
    cfg.add_field(FieldDefinition(name="b", bits=8))
    assert cfg.get_total_bits() == 12
    assert cfg.get_field("a").bit_position == (3, 0)   # first added -> lowest bits
    assert cfg.get_field("b").bit_position == (11, 4)  # last added -> highest bits


def test_lsb_first_mode_bit_positions_pinned():
    """Pin the legacy lsb_first packing semantics: FIRST field added gets highest bits."""
    cfg = FieldConfig(lsb_first=True)
    cfg.add_field(FieldDefinition(name="a", bits=4))
    cfg.add_field(FieldDefinition(name="b", bits=8))
    assert cfg.get_total_bits() == 12
    assert cfg.get_field("a").bit_position == (11, 8)  # first added -> highest bits
    assert cfg.get_field("b").bit_position == (7, 0)   # last added -> lowest bits


def test_validate_and_create_does_not_mutate_caller_dict():
    """validate_and_create must correct issues on a copy, not the caller's dict."""
    field_dict = {
        "ctrl": {"format": "hex"},                      # missing 'bits'
        "data": {"bits": "16", "format": "invalid"},    # str bits, bad format
    }
    import copy
    snapshot = copy.deepcopy(field_dict)
    FieldConfig.validate_and_create(field_dict)
    assert field_dict == snapshot, "caller's dict was mutated"


def test_validate_and_create_keeps_msb_lsb_swapped_field():
    """An active_bits range with msb < lsb is corrected (swapped), not dropped."""
    field_dict = {"flags": {"bits": 8, "active_bits": (2, 5)}}  # msb < lsb
    cfg = FieldConfig.validate_and_create(field_dict)
    assert cfg.has_field("flags"), "field with msb < lsb active_bits was dropped"
    assert cfg.get_field("flags").active_bits == (5, 2)


def test_validate_and_create_raises_on_msb_lsb_swap_when_strict():
    with pytest.raises(ValueError, match="invalid 'active_bits' range"):
        FieldConfig.validate_and_create(
            {"flags": {"bits": 8, "active_bits": (2, 5)}}, raise_errors=True
        )


def test_validate_and_create_rejects_non_dict_props():
    """Non-dict field properties are reported, not crashed on."""
    cfg = FieldConfig.validate_and_create({"bogus": 42, "good": {"bits": 8}})
    assert not cfg.has_field("bogus")
    assert cfg.has_field("good")
    with pytest.raises(ValueError, match="must be a dict"):
        FieldConfig.validate_and_create({"bogus": 42}, raise_errors=True)


def test_lsb_first_and_msb_first_produce_different_orderings():
    """Whatever the semantics, the two modes must produce different bit assignments."""
    msb_cfg = FieldConfig()
    msb_cfg.add_field(FieldDefinition(name="first", bits=4))
    msb_cfg.add_field(FieldDefinition(name="second", bits=4))

    lsb_cfg = FieldConfig(lsb_first=True)
    lsb_cfg.add_field(FieldDefinition(name="first", bits=4))
    lsb_cfg.add_field(FieldDefinition(name="second", bits=4))

    msb_first_pos = msb_cfg.get_field("first").bit_position
    lsb_first_pos = lsb_cfg.get_field("first").bit_position
    assert msb_first_pos != lsb_first_pos, (
        "Default and lsb_first should produce different orderings"
    )
