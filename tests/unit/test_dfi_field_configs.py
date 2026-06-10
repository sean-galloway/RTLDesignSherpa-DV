"""Unit tests for DFI field-config builders (issue #16)."""

from __future__ import annotations

from CocoTBFramework.components.dfi.dfi_field_configs import (
    control_field_config,
    read_data_field_config,
    write_data_field_config,
)
from CocoTBFramework.components.dfi.dfi_signals import MemoryType


# ---------------------------------------------------------------------
# Control interface field configs
# ---------------------------------------------------------------------


def test_control_ddr3_includes_reset_n_and_odt():
    cfg = control_field_config(memory_type=MemoryType.DDR3)
    names = list(cfg.field_names())
    assert "reset_n" in names  # DDR3-only
    assert "odt" in names      # DDR2/DDR3
    assert "bank" in names     # DDR1+


def test_control_ddr2_includes_odt_excludes_reset_n():
    cfg = control_field_config(memory_type=MemoryType.DDR2)
    names = list(cfg.field_names())
    assert "odt" in names
    assert "reset_n" not in names


def test_control_lpddr2_excludes_idled_signals():
    cfg = control_field_config(memory_type=MemoryType.LPDDR2)
    names = list(cfg.field_names())
    assert "address" in names
    # bank/ras_n/cas_n/we_n are held idle for LPDDR2 — not in the config
    assert "bank" not in names
    assert "ras_n" not in names
    assert "cas_n" not in names
    assert "we_n" not in names


def test_control_width_arguments_propagate():
    cfg = control_field_config(
        memory_type=MemoryType.DDR3,
        addr_width=20,
        bank_width=4,
    )
    addr_field = cfg.get_field("address")
    bank_field = cfg.get_field("bank")
    assert addr_field.bits == 20
    assert bank_field.bits == 4


# ---------------------------------------------------------------------
# Write data field configs
# ---------------------------------------------------------------------


def test_write_data_fields_present():
    cfg = write_data_field_config(memory_type=MemoryType.DDR3, data_width=64)
    names = set(cfg.field_names())
    assert names == {"wrdata", "wrdata_en", "wrdata_mask"}


def test_write_data_mask_width_is_data_width_div_8():
    cfg = write_data_field_config(memory_type=MemoryType.DDR3, data_width=64)
    assert cfg.get_field("wrdata").bits == 64
    assert cfg.get_field("wrdata_mask").bits == 8  # 64 / 8


def test_write_data_mask_width_for_32_bit_path():
    cfg = write_data_field_config(memory_type=MemoryType.DDR3, data_width=32)
    assert cfg.get_field("wrdata_mask").bits == 4


# ---------------------------------------------------------------------
# Read data field configs
# ---------------------------------------------------------------------


def test_read_data_ddr3_excludes_dnv():
    cfg = read_data_field_config(memory_type=MemoryType.DDR3)
    names = list(cfg.field_names())
    assert "rddata_dnv" not in names


def test_read_data_lpddr2_includes_dnv():
    cfg = read_data_field_config(memory_type=MemoryType.LPDDR2)
    names = list(cfg.field_names())
    assert "rddata_dnv" in names
    assert cfg.get_field("rddata_dnv").bits == 8  # data_width / 8


def test_read_data_widths():
    cfg = read_data_field_config(
        memory_type=MemoryType.DDR3,
        data_width=128,
        rd_valid_width=2,
    )
    assert cfg.get_field("rddata").bits == 128
    assert cfg.get_field("rddata_valid").bits == 2
