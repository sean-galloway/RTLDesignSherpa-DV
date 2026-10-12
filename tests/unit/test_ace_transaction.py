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

def test_arsnoop_encodings_match_table_d3_7():
    """IHI 0022H.c Table D3-7: every ARSNOOP[3:0] value."""
    from CocoTBFramework.components.ace.ace_transaction import ARSnoop
    expected = {
        "READ_ONCE": 0b0000, "READ_SHARED": 0b0001, "READ_CLEAN": 0b0010,
        "READ_NOT_SHARED_DIRTY": 0b0011, "READ_UNIQUE": 0b0111,
        "CLEAN_UNIQUE": 0b1011, "MAKE_UNIQUE": 0b1100,
        "CLEAN_SHARED": 0b1000, "CLEAN_INVALID": 0b1001,
        "MAKE_INVALID": 0b1101, "DVM_COMPLETE": 0b1110, "DVM_MESSAGE": 0b1111,
    }
    assert {m.name: m.value for m in ARSnoop} == expected


def test_awsnoop_encodings_match_table_d3_8():
    """IHI 0022H.c Table D3-8: every AWSNOOP[2:0] value."""
    from CocoTBFramework.components.ace.ace_transaction import AWSnoop
    expected = {
        "WRITE_UNIQUE": 0b000, "WRITE_LINE_UNIQUE": 0b001, "WRITE_CLEAN": 0b010,
        "WRITE_BACK": 0b011, "EVICT": 0b100, "WRITE_EVICT": 0b101,
    }
    assert {m.name: m.value for m in AWSnoop} == expected


def test_compat_names_resolve_to_correct_channel():
    """The deprecated combined namespace keeps every old name, unaliased."""
    from CocoTBFramework.components.ace.ace_transaction import ARSnoop, AWSnoop
    assert ACETransactionType.READ_NOT_SHARED_DIRTY is ARSnoop.READ_NOT_SHARED_DIRTY
    assert int(ACETransactionType.READ_NOT_SHARED_DIRTY) == 0b0011
    assert ACETransactionType.WRITE_BACK is AWSnoop.WRITE_BACK
    assert ACETransactionType.WRITE_BACK.name == "WRITE_BACK"
    assert int(ACETransactionType.EVICT) == 0b100
    # Write names no longer alias read members
    assert ACETransactionType.WRITE_UNIQUE.name == "WRITE_UNIQUE"
    assert ACETransactionType.WRITE_LINE_UNIQUE.name == "WRITE_LINE_UNIQUE"
    assert ACETransactionType.WRITE_CLEAN.name == "WRITE_CLEAN"
    for name in ("READ_SHARED", "READ_UNIQUE", "CLEAN_UNIQUE", "MAKE_UNIQUE",
                 "READ_ONCE", "READ_CLEAN"):
        assert getattr(ACETransactionType, name) is ARSnoop[name]
    names = [t.name for t in ACETransactionType]
    assert len(names) == len(set(names)) == len(ACETransactionType) == 12
    with pytest.raises(TypeError):
        ACETransactionType(3)


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
