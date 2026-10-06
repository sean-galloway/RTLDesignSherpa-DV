# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for ACE transaction types and CRRESP helpers."""

import pytest

from CocoTBFramework.components.ace.ace_transaction import (
    ACETransactionType,
    CRRESP,
    CRRESPBit,
    CacheState,
    SnoopType,
)


# ---------------------------------------------------------------------------
# Transaction / snoop enum membership
# ---------------------------------------------------------------------------

def test_research_subset_transaction_types():
    assert ACETransactionType.READ_SHARED.value == 0x1
    assert ACETransactionType.READ_UNIQUE.value == 0x7
    assert ACETransactionType.CLEAN_UNIQUE.value == 0xB
    assert ACETransactionType.MAKE_UNIQUE.value == 0xC
    assert ACETransactionType.WRITE_BACK.value == 0x3
    assert ACETransactionType.EVICT.value == 0x5


def test_full_ace_transaction_types_present():
    names = {t.name for t in ACETransactionType}
    assert {"READ_ONCE", "READ_CLEAN", "READ_NOT_SHARED_DIRTY"}.issubset(names)
    # Write-side types collide with read-side values in the shared encoding
    # space, so they are exposed as aliases accessible by attribute.
    assert hasattr(ACETransactionType, "WRITE_UNIQUE")
    assert hasattr(ACETransactionType, "WRITE_LINE_UNIQUE")
    assert hasattr(ACETransactionType, "WRITE_CLEAN")


def test_snoop_type_membership():
    names = {t.name for t in SnoopType}
    expected = {"READ_ONCE", "READ_SHARED", "READ_UNIQUE",
                "CLEAN_SHARED", "CLEAN_INVALID", "MAKE_INVALID"}
    assert names == expected


# ---------------------------------------------------------------------------
# CRRESP bit positions
# ---------------------------------------------------------------------------

def test_crresp_bit_positions():
    assert CRRESPBit.DATA_TRANSFER == 0
    assert CRRESPBit.ERROR == 1
    assert CRRESPBit.PASS_DIRTY == 2
    assert CRRESPBit.IS_SHARED == 3
    assert CRRESPBit.WAS_UNIQUE == 4


def test_crresp_from_bits():
    cr = CRRESP.from_bits(data_transfer=True, pass_dirty=True, is_shared=True)
    assert cr.data_transfer
    assert cr.pass_dirty
    assert cr.is_shared
    assert not cr.error
    assert not cr.was_unique
    assert int(cr) == (1 << 0) | (1 << 2) | (1 << 3)


# ---------------------------------------------------------------------------
# CRRESP validity per snoop type
# ---------------------------------------------------------------------------

def test_make_invalid_forbids_data_transfer():
    cr = CRRESP.from_bits(data_transfer=True)
    valid, msg = cr.validate_for_snoop(SnoopType.MAKE_INVALID)
    assert not valid
    assert "MakeInvalid forbids DataTransfer" in msg


def test_read_shared_allows_data_transfer():
    cr = CRRESP.from_bits(data_transfer=True, pass_dirty=True, is_shared=True)
    assert cr.validate_for_snoop(SnoopType.READ_SHARED)[0]


def test_pass_dirty_without_data_transfer_is_invalid():
    cr = CRRESP.from_bits(pass_dirty=True)
    valid, msg = cr.validate_for_snoop(SnoopType.READ_UNIQUE)
    assert not valid
    assert "PassDirty set without DataTransfer" in msg


@pytest.mark.parametrize("snoop_type", list(SnoopType))
def test_zero_crresp_is_always_valid(snoop_type):
    assert CRRESP(0).validate_for_snoop(snoop_type)[0]


# ---------------------------------------------------------------------------
# Cache states
# ---------------------------------------------------------------------------

def test_cache_state_values():
    assert CacheState.INVALID.value == "I"
    assert CacheState.SHARED.value == "S"
    assert CacheState.EXCLUSIVE.value == "E"
    assert CacheState.MODIFIED.value == "M"
    assert CacheState.OWNED.value == "O"
