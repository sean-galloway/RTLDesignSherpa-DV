# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACE transaction types and CRRESP helpers
# Purpose: Enumerations and bitfield helpers for ACE coherent transactions.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""ACE transaction types and CRRESP bitfield helpers.

This module defines the coherent transaction types used by ACE (ARSNOOP and
AWSNOOP encodings), the snoop transaction types used on the AC channel, and a
CRRESP bitfield helper with per-snoop-type validity checking.

The bit positions for CRRESP follow Arm IHI 0022H:

- bit[0]: DataTransfer
- bit[1]: Error
- bit[2]: PassDirty
- bit[3]: IsShared
- bit[4]: WasUnique
"""

from enum import Enum, IntEnum
from typing import Optional, Tuple


class ACETransactionType(IntEnum):
    """ACE coherent transaction types carried on ARSNOOP / AWSNOOP.

    The six values in the onyx D2 research subset are listed first and
    highlighted in the docstrings. The remaining values are the full ACE set
    supported by the cache-ip family contract.
    """

    # Research subset (onyx D2)
    READ_SHARED = 0x1
    """Fetch a line to read; other caches may keep Shared copies."""

    READ_UNIQUE = 0x7
    """Fetch a line to write; all other copies must be invalidated."""

    CLEAN_UNIQUE = 0xB
    """Requester already holds the line; make this copy Unique (no data)."""

    MAKE_UNIQUE = 0xC
    """Like CleanUnique but requester will overwrite the whole line."""

    WRITE_BACK = 0x3
    """Retire a dirty line to memory; manager must merge data into DRAM."""

    EVICT = 0x5
    """Retire a clean line; hint, no data and no DRAM write needed."""

    # Full ACE read-side types (completeness)
    READ_ONCE = 0x0
    READ_CLEAN = 0x2
    READ_NOT_SHARED_DIRTY = 0x4

    # Full ACE write-side types (completeness)
    WRITE_UNIQUE = 0x0
    WRITE_LINE_UNIQUE = 0x1
    WRITE_CLEAN = 0x2


class SnoopType(IntEnum):
    """Snoop transaction types carried on ACSNOOP[3:0]."""

    READ_ONCE = 0x0
    READ_SHARED = 0x1
    READ_UNIQUE = 0x7
    CLEAN_SHARED = 0x8
    CLEAN_INVALID = 0x9
    MAKE_INVALID = 0xC


class CRRESPBit(IntEnum):
    """CRRESP bit positions per Arm IHI 0022H."""

    DATA_TRANSFER = 0
    ERROR = 1
    PASS_DIRTY = 2
    IS_SHARED = 3
    WAS_UNIQUE = 4


class CacheState(str, Enum):
    """Gem5-style stable cache-line states for the snoop responder model."""

    INVALID = "I"
    SHARED = "S"
    EXCLUSIVE = "E"
    MODIFIED = "M"
    OWNED = "O"  # Optional; supported where a manager can accept Owned state


class CRRESP:
    """CRRESP bitfield helper with validity checking per snoop type."""

    def __init__(self, value: int = 0):
        """Initialize CRRESP from a 5-bit integer."""
        self.value = value & 0x1F

    @classmethod
    def from_bits(
        cls,
        data_transfer: bool = False,
        error: bool = False,
        pass_dirty: bool = False,
        is_shared: bool = False,
        was_unique: bool = False,
    ) -> "CRRESP":
        """Create a CRRESP from individual bit values."""
        value = 0
        if data_transfer:
            value |= 1 << CRRESPBit.DATA_TRANSFER
        if error:
            value |= 1 << CRRESPBit.ERROR
        if pass_dirty:
            value |= 1 << CRRESPBit.PASS_DIRTY
        if is_shared:
            value |= 1 << CRRESPBit.IS_SHARED
        if was_unique:
            value |= 1 << CRRESPBit.WAS_UNIQUE
        return cls(value)

    @property
    def data_transfer(self) -> bool:
        return bool(self.value & (1 << CRRESPBit.DATA_TRANSFER))

    @property
    def error(self) -> bool:
        return bool(self.value & (1 << CRRESPBit.ERROR))

    @property
    def pass_dirty(self) -> bool:
        return bool(self.value & (1 << CRRESPBit.PASS_DIRTY))

    @property
    def is_shared(self) -> bool:
        return bool(self.value & (1 << CRRESPBit.IS_SHARED))

    @property
    def was_unique(self) -> bool:
        return bool(self.value & (1 << CRRESPBit.WAS_UNIQUE))

    def has(self, bit: CRRESPBit) -> bool:
        """Check whether a specific CRRESP bit is set."""
        return bool(self.value & (1 << int(bit)))

    def validate_for_snoop(self, snoop_type: SnoopType) -> Tuple[bool, Optional[str]]:
        """
        Check CRRESP validity for a given snoop type.

        Returns:
            Tuple of (is_valid, error_message or None)
        """
        # MakeInvalid must not transfer data.
        if snoop_type == SnoopType.MAKE_INVALID and self.data_transfer:
            return False, "MakeInvalid forbids DataTransfer"

        # PassDirty without DataTransfer is not legal for this family: dirty
        # responsibility only moves together with the data.
        if self.pass_dirty and not self.data_transfer:
            return False, "PassDirty set without DataTransfer"

        return True, None

    def __int__(self) -> int:
        return self.value

    def __eq__(self, other) -> bool:
        if isinstance(other, CRRESP):
            return self.value == other.value
        if isinstance(other, int):
            return self.value == other
        return NotImplemented

    def __repr__(self) -> str:
        bits = []
        if self.data_transfer:
            bits.append("DataTransfer")
        if self.error:
            bits.append("Error")
        if self.pass_dirty:
            bits.append("PassDirty")
        if self.is_shared:
            bits.append("IsShared")
        if self.was_unique:
            bits.append("WasUnique")
        return f"CRRESP(0x{self.value:02X}, {', '.join(bits) if bits else 'none'})"


# Convenience aliases matching the spec text
CRRESP_DATA_TRANSFER = 1 << CRRESPBit.DATA_TRANSFER
CRRESP_ERROR = 1 << CRRESPBit.ERROR
CRRESP_PASS_DIRTY = 1 << CRRESPBit.PASS_DIRTY
CRRESP_IS_SHARED = 1 << CRRESPBit.IS_SHARED
CRRESP_WAS_UNIQUE = 1 << CRRESPBit.WAS_UNIQUE
