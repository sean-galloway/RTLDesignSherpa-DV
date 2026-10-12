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

This module defines the coherent transaction types used by ACE (``ARSnoop``
for ARSNOOP, ``AWSnoop`` for AWSNOOP, plus the deprecated combined
``ACETransactionType`` namespace), the snoop transaction types used on the AC channel, and a
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


class ARSnoop(IntEnum):
    """ARSNOOP[3:0] encodings, Arm IHI 0022H.c Table D3-7.

    Read-channel and write-channel snoop encodings overlap numerically
    (0b0011 is ReadNotSharedDirty on AR and WriteBack on AW), so they live in
    two enums. Use ``ARSnoop`` for ``snoop_type`` on reads and ``AWSnoop`` on
    writes.

    0b0000 is ReadOnce for a Shareable ARDOMAIN; the same encoding is
    ReadNoSnoop when ARDOMAIN is Non-shareable or System, and Barrier when
    ARBAR[0] is 1. Those are told apart by ARDOMAIN/ARBAR, not by ARSNOOP, so
    they are not separate members here. All other encodings are Reserved.
    """

    # Coherent
    READ_ONCE = 0b0000
    READ_SHARED = 0b0001
    READ_CLEAN = 0b0010
    READ_NOT_SHARED_DIRTY = 0b0011
    READ_UNIQUE = 0b0111
    CLEAN_UNIQUE = 0b1011
    MAKE_UNIQUE = 0b1100

    # Cache maintenance
    CLEAN_SHARED = 0b1000
    CLEAN_INVALID = 0b1001
    MAKE_INVALID = 0b1101

    # DVM
    DVM_COMPLETE = 0b1110
    DVM_MESSAGE = 0b1111


class AWSnoop(IntEnum):
    """AWSNOOP[2:0] encodings, Arm IHI 0022H.c Table D3-8.

    0b000 is WriteUnique for a Shareable AWDOMAIN; the same encoding is
    WriteNoSnoop when AWDOMAIN is Non-shareable or System, and Barrier when
    AWBAR[0] is 1. All other encodings are Reserved.
    """

    WRITE_UNIQUE = 0b000
    WRITE_LINE_UNIQUE = 0b001
    WRITE_CLEAN = 0b010
    WRITE_BACK = 0b011
    EVICT = 0b100
    WRITE_EVICT = 0b101


class _ACETransactionTypeMeta(type):
    """Make the compatibility namespace iterable like the enum it replaced."""

    def __iter__(cls):
        return iter(cls._MEMBERS)

    def __len__(cls):
        return len(cls._MEMBERS)

    def __contains__(cls, item):
        return item in cls._MEMBERS


class ACETransactionType(metaclass=_ACETransactionTypeMeta):
    """Deprecated compatibility namespace; use ``ARSnoop`` / ``AWSnoop``.

    This used to be one IntEnum holding both the ARSNOOP and AWSNOOP
    encodings. Because the two encoding spaces overlap, the write-side names
    silently aliased read-side members (``WRITE_BACK`` and
    ``READ_NOT_SHARED_DIRTY`` cannot both be 0b0011 in one IntEnum), and two
    values were wrong (ReadNotSharedDirty was 0x4, Evict was 0x5).

    Every old attribute name still resolves, now to the correct member of
    ``ARSnoop`` or ``AWSnoop``, so ``ACETransactionType.WRITE_BACK`` is
    ``AWSnoop.WRITE_BACK`` (0b011) and ``ACETransactionType.READ_NOT_SHARED_DIRTY``
    is ``ARSnoop.READ_NOT_SHARED_DIRTY`` (0b0011). Iterating yields the read
    members, then the write members. Constructing from a bare value is refused,
    because a value alone does not say which channel it belongs to.
    """

    READ_SHARED = ARSnoop.READ_SHARED
    READ_UNIQUE = ARSnoop.READ_UNIQUE
    CLEAN_UNIQUE = ARSnoop.CLEAN_UNIQUE
    MAKE_UNIQUE = ARSnoop.MAKE_UNIQUE
    READ_ONCE = ARSnoop.READ_ONCE
    READ_CLEAN = ARSnoop.READ_CLEAN
    READ_NOT_SHARED_DIRTY = ARSnoop.READ_NOT_SHARED_DIRTY

    WRITE_BACK = AWSnoop.WRITE_BACK
    EVICT = AWSnoop.EVICT
    WRITE_UNIQUE = AWSnoop.WRITE_UNIQUE
    WRITE_LINE_UNIQUE = AWSnoop.WRITE_LINE_UNIQUE
    WRITE_CLEAN = AWSnoop.WRITE_CLEAN

    _MEMBERS = (
        ARSnoop.READ_ONCE, ARSnoop.READ_SHARED, ARSnoop.READ_CLEAN,
        ARSnoop.READ_NOT_SHARED_DIRTY, ARSnoop.READ_UNIQUE,
        ARSnoop.CLEAN_UNIQUE, ARSnoop.MAKE_UNIQUE,
        AWSnoop.WRITE_UNIQUE, AWSnoop.WRITE_LINE_UNIQUE, AWSnoop.WRITE_CLEAN,
        AWSnoop.WRITE_BACK, AWSnoop.EVICT,
    )

    def __new__(cls, value):
        raise TypeError(
            f"ACETransactionType({value!r}) is ambiguous: ARSNOOP and AWSNOOP "
            "encodings overlap. Use ARSnoop(value) or AWSnoop(value)."
        )


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
