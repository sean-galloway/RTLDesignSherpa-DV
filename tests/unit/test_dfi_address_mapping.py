"""Unit tests for the DFI BFM address mapping (issue #16).

Models DRAMsim3-style late-binding decode: a mapping string like
``"row|bank|col"`` dictates the MSB→LSB bit-slice order, geometry
(num_ranks, num_banks, num_rows, num_cols) sets the field widths.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dram_state import AddressMapping


# ---------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------


def test_default_mapping_is_row_bank_col():
    m = AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)
    assert m.mapping == "row|bank|col"


def test_rejects_non_power_of_two_banks():
    with pytest.raises(ValueError, match="power of 2"):
        AddressMapping(num_ranks=1, num_banks=6, num_rows=8192, num_cols=1024)


def test_rejects_non_power_of_two_rows():
    with pytest.raises(ValueError, match="power of 2"):
        AddressMapping(num_ranks=1, num_banks=8, num_rows=8000, num_cols=1024)


def test_rejects_unknown_field_in_mapping():
    with pytest.raises(ValueError, match="unknown field"):
        AddressMapping(
            mapping="row|bogus|col",
            num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
        )


def test_rejects_duplicate_field_in_mapping():
    with pytest.raises(ValueError, match="duplicate"):
        AddressMapping(
            mapping="row|bank|row",
            num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
        )


def test_rejects_missing_required_field():
    """col must appear in the mapping (you can't address into a row
    without it). Same for bank when num_banks > 1."""
    with pytest.raises(ValueError, match="missing"):
        AddressMapping(
            mapping="row|bank",  # no col
            num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
        )


def test_rank_field_optional_when_single_rank():
    """Single-rank DIMM (the MT47H64M16HR-25:H case): 'rank' may be
    omitted from the mapping string entirely."""
    m = AddressMapping(
        mapping="row|bank|col",
        num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
    )
    rank, bank, row, col = m.flat_to_tuple(0)
    assert rank == 0


def test_rank_field_required_when_multi_rank():
    with pytest.raises(ValueError, match="rank"):
        AddressMapping(
            mapping="row|bank|col",  # missing rank
            num_ranks=2, num_banks=8, num_rows=8192, num_cols=1024,
        )


# ---------------------------------------------------------------------
# flat_to_tuple / tuple_to_flat round-trip
# ---------------------------------------------------------------------


def test_round_trip_single_rank():
    m = AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)
    for r, b, row, col in [
        (0, 0, 0, 0),
        (0, 7, 8191, 1023),
        (0, 3, 0x100, 0x55),
        (0, 5, 0x1234, 0x2AA),
    ]:
        flat = m.tuple_to_flat(r, b, row, col)
        assert m.flat_to_tuple(flat) == (r, b, row, col)


def test_round_trip_multi_rank():
    m = AddressMapping(
        mapping="rank|row|bank|col",
        num_ranks=2, num_banks=8, num_rows=8192, num_cols=1024,
    )
    for r, b, row, col in [
        (0, 0, 0, 0),
        (1, 7, 8191, 1023),
        (1, 4, 0xABC, 0x123),
    ]:
        flat = m.tuple_to_flat(r, b, row, col)
        assert m.flat_to_tuple(flat) == (r, b, row, col)


# ---------------------------------------------------------------------
# Bit-slice order matches the mapping string
# ---------------------------------------------------------------------


def test_row_bank_col_layout():
    """For row|bank|col with 8 banks (3b), 8192 rows (13b), 1024 cols (10b):
        flat[25:13] = row, flat[12:10] = bank, flat[9:0] = col
    """
    m = AddressMapping(
        mapping="row|bank|col",
        num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
    )
    # row=1, bank=0, col=0 → bit 13 set
    assert m.tuple_to_flat(0, 0, 1, 0) == (1 << 13)
    # row=0, bank=1, col=0 → bit 10 set
    assert m.tuple_to_flat(0, 1, 0, 0) == (1 << 10)
    # row=0, bank=0, col=1 → bit 0 set
    assert m.tuple_to_flat(0, 0, 0, 1) == 1


def test_row_col_bank_layout_swaps_bank_and_col():
    """row|col|bank places bank in the LSBs — column-major-ish layout.
        flat[25:13] = row, flat[12:3] = col, flat[2:0] = bank
    """
    m = AddressMapping(
        mapping="row|col|bank",
        num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
    )
    # bank=1 → bit 0 set
    assert m.tuple_to_flat(0, 1, 0, 0) == 1
    # col=1 → bit 3 set (above bank bits)
    assert m.tuple_to_flat(0, 0, 0, 1) == (1 << 3)


# ---------------------------------------------------------------------
# Range checking
# ---------------------------------------------------------------------


def test_tuple_to_flat_rejects_out_of_range():
    m = AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)
    with pytest.raises(ValueError, match="bank"):
        m.tuple_to_flat(0, 8, 0, 0)  # bank 8 invalid (0..7)
    with pytest.raises(ValueError, match="row"):
        m.tuple_to_flat(0, 0, 8192, 0)
    with pytest.raises(ValueError, match="col"):
        m.tuple_to_flat(0, 0, 0, 1024)


# ---------------------------------------------------------------------
# total_size — number of distinct flat addresses
# ---------------------------------------------------------------------


def test_total_size_matches_geometry_product():
    m = AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)
    assert m.total_size == 1 * 8 * 8192 * 1024
