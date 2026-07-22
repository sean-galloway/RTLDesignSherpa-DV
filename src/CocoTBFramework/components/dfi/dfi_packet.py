# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Packet types for the three MVP DFI sub-interfaces (issue #16).

One packet per cycle of activity on a sub-interface:

- :class:`DFIControlPacket` — one cycle's worth of control-interface
  signals (address/bank/cmd/cs/cke/odt/reset, gated on memory type)
- :class:`DFIWriteDataPacket` — one beat of wrdata + wrdata_en + mask
- :class:`DFIReadDataPacket` — one beat of rddata + rddata_valid (+ dnv
  for LPDDR2)

Each packet captures the **memory-type-gated** signal set as optional
fields (default 0 when the signal isn't applicable to the target
memory). This keeps the packet API uniform — testbenches don't need
per-version conditional packing.

A separate convenience builder :meth:`DFIControlPacket.from_command`
translates a high-level DRAM command (ACT, RD, WR, PRE, REF, NOP) into
the right combination of RAS/CAS/WE/CS/CKE bits for the target memory
type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .dfi_signals import MemoryType

# ----------------------------------------------------------------------
# DRAM command encoding (high-level → RAS/CAS/WE/CS bits)
# ----------------------------------------------------------------------


class DRAMCommand(str, Enum):
    """High-level DRAM command codes. Maps to RAS/CAS/WE/CS bit pattern
    via :meth:`DFIControlPacket.from_command`."""

    NOP = "nop"           # No operation
    ACT = "activate"      # Activate row
    RD = "read"           # Read
    RDA = "read_auto"     # Read with auto-precharge
    WR = "write"          # Write
    WRA = "write_auto"    # Write with auto-precharge
    PRE = "precharge"     # Precharge bank
    PREA = "precharge_all"  # Precharge all banks
    REF = "refresh"       # Auto refresh
    SRE = "self_refresh_entry"
    SRX = "self_refresh_exit"
    PDE = "powerdown_entry"
    PDX = "powerdown_exit"
    MRS = "mode_register_set"
    ZQCS = "zq_calibration_short"
    ZQCL = "zq_calibration_long"
    DESEL = "deselect"    # CS_n high — no command


# Encoding: (cs_n, ras_n, cas_n, we_n) for DDR3 (DDR2/DDR1 mostly same).
# 0 = asserted (active-low), 1 = deasserted.
# Per JEDEC JESD79-3F Table 67. LPDDR2 uses a totally different CA bus
# encoding and doesn't use these signals — call ``encode_lpddr2_ca``
# instead.
_DDR3_ENCODING = {
    DRAMCommand.DESEL: (1, 1, 1, 1),
    DRAMCommand.NOP:   (0, 1, 1, 1),
    DRAMCommand.ACT:   (0, 0, 1, 1),
    DRAMCommand.RD:    (0, 1, 0, 1),
    DRAMCommand.RDA:   (0, 1, 0, 1),  # auto-precharge encoded in addr[10]
    DRAMCommand.WR:    (0, 1, 0, 0),
    DRAMCommand.WRA:   (0, 1, 0, 0),  # auto-precharge encoded in addr[10]
    DRAMCommand.PRE:   (0, 0, 1, 0),
    DRAMCommand.PREA:  (0, 0, 1, 0),  # all-banks encoded in addr[10]
    DRAMCommand.REF:   (0, 0, 0, 1),
    DRAMCommand.MRS:   (0, 0, 0, 0),
    DRAMCommand.ZQCS:  (0, 1, 1, 0),  # JESD79-3F Table 67, addr[10]=0
    DRAMCommand.ZQCL:  (0, 1, 1, 0),  # JESD79-3F Table 67, addr[10]=1
}


# ----------------------------------------------------------------------
# DFIControlPacket — one cycle of control-interface signals
# ----------------------------------------------------------------------


@dataclass
class DFIControlPacket:
    """One cycle's worth of DFI control-interface signal values.

    Every field corresponds to a signal in DFI v2.1 Table 2. Fields
    that don't apply to a given memory type stay at their defaults
    (typically 0 or 1 to match the deasserted-idle state per spec) and
    the BFM simply doesn't drive the corresponding signal if it wasn't
    instantiated.
    """

    # Universal (all memory types)
    address: int = 0
    cke: int = 0
    cs_n: int = 1   # deasserted (idle)

    # DDR1/LPDDR1/DDR2/DDR3 (LPDDR2 holds idle)
    bank: int = 0
    cas_n: int = 1
    ras_n: int = 1
    we_n: int = 1

    # DDR2/DDR3 only
    odt: int = 0

    # DDR3 only
    reset_n: int = 1   # deasserted (not in reset)

    # Capture-side metadata. Populated by DFIMonitor; ignored by drivers.
    cmd: Optional["DRAMCommand"] = None
    timestamp_ns: float = 0.0

    @classmethod
    def from_command(
        cls,
        cmd: DRAMCommand,
        *,
        memory_type: MemoryType,
        address: int = 0,
        bank: int = 0,
        cs_n: int = 0,    # asserted to actually issue the command
        cke: int = 1,     # clock-enabled
        odt: int = 0,
        auto_precharge: bool = False,
        all_banks: bool = False,
    ) -> "DFIControlPacket":
        """Build a control packet for a high-level DRAM command.

        Handles the (cs_n, ras_n, cas_n, we_n) encoding for the target
        memory and the addr[10] usage for auto-precharge / all-banks
        variants.
        """
        if memory_type in (MemoryType.LPDDR2, MemoryType.LPDDR3):
            # LPDDR2/3 carry the command on the 20-bit dfi_address CA
            # bus and hold bank/ras_n/cas_n/we_n at idle per DFI v2.1
            # Table 1. The ``address`` parameter is interpreted as
            # row for ACT, col for RD/WR/etc.
            from .lpddr_ca import encode_lpddr2_ca
            is_rdwr = cmd in (
                DRAMCommand.RD, DRAMCommand.RDA,
                DRAMCommand.WR, DRAMCommand.WRA,
            )
            ca_word = encode_lpddr2_ca(
                cmd,
                bank=bank,
                row=address if cmd == DRAMCommand.ACT else 0,
                col=address if is_rdwr else 0,
                auto_precharge=auto_precharge,
                all_banks=all_banks,
            )
            return cls(
                address=ca_word,
                bank=0,            # held idle per spec
                cke=cke,
                cs_n=cs_n,         # still asserted to issue the command
                ras_n=1, cas_n=1, we_n=1,   # held idle per spec Table 1
                odt=odt,
            )

        cs_bit, ras_bit, cas_bit, we_bit = _DDR3_ENCODING[cmd]
        # The cs_n the user passed is the chip we're targeting; combine
        # with the spec's cs_n encoding (0 for almost everything except
        # DESEL/NOP-style idle).
        effective_cs = cs_n if cs_bit == 0 else 1

        effective_addr = address
        if auto_precharge and cmd in (DRAMCommand.RD, DRAMCommand.RDA,
                                       DRAMCommand.WR, DRAMCommand.WRA):
            effective_addr |= (1 << 10)
        if all_banks and cmd == DRAMCommand.PREA:
            effective_addr |= (1 << 10)

        return cls(
            address=effective_addr,
            bank=bank,
            cke=cke,
            cs_n=effective_cs,
            ras_n=ras_bit,
            cas_n=cas_bit,
            we_n=we_bit,
            odt=odt,
        )


# ----------------------------------------------------------------------
# DFIWriteDataPacket — one beat of write data
# ----------------------------------------------------------------------


@dataclass
class DFIWriteDataPacket:
    """One beat of the DFI write-data interface."""

    wrdata: int = 0
    wrdata_en: int = 0    # bit per data slice; asserted during valid beats
    wrdata_mask: int = 0  # bit per 8 wrdata bits; 1=mask (don't write)

    # Capture-side metadata. Populated by DFIMonitor; ignored by drivers.
    timestamp_ns: float = 0.0


# ----------------------------------------------------------------------
# DFIReadDataPacket — one beat of read data
# ----------------------------------------------------------------------


@dataclass
class DFIReadDataPacket:
    """One beat of the DFI read-data interface."""

    rddata: int = 0
    rddata_valid: int = 0  # bit per slice; asserted during valid beats
    rddata_dnv: int = 0    # LPDDR2 only: data-not-valid byte mask

    # Capture-side metadata. Populated by DFIMonitor; ignored by drivers.
    timestamp_ns: float = 0.0
