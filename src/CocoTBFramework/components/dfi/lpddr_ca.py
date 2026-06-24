# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LPDDR2/3 CA-bus encoding for the DFI BFM.

Per DFI v2.1 Table 1, LPDDR2 (and LPDDR3 by inheritance) replaces the
DDR-style separate ``dfi_ras_n``/``dfi_cas_n``/``dfi_we_n``/``dfi_bank``
control signals with a multiplexed Command/Address (CA) bus carried in
the ``dfi_address`` field:

* ``dfi_address`` width ≥ 20 bits
* ``dfi_address[9:0]``   = CA cycle 1 (rising-edge slot per Table 1)
* ``dfi_address[19:10]`` = CA cycle 2 (falling-edge slot)
* ``dfi_bank``, ``dfi_ras_n``, ``dfi_cas_n``, ``dfi_we_n`` held at idle

The PHY is responsible for splitting the 20-bit word into the two 10-bit
LPDDR DDR cycles delivered to the DRAM.

This module provides a BFM-friendly, deterministic round-trippable
encoding of high-level :class:`DRAMCommand` values into the 20-bit CA
word and back. The bit layout follows the spirit of JESD209-2 (CA[2:0]
carries the command class on the first cycle, continuation marker 0b010
on the second) but uses a simplified, BFM-internal packing of bank/row/
col bits — round-trip via ``decode`` is byte-exact, but it is *not* a
silicon-faithful re-creation of the JESD209-2 bit-by-bit field layout
(which packs row bits in a non-contiguous, latency-driven order).

For BFM verification this is what matters:
  - the same packing is used on both ends (master + slave)
  - the slave reconstructs (cmd, bank, row, col, ap, all_banks) so the
    state model / memory commit path works as it does for DDR
  - command codes match the spec's CA1[2:0] so anything that does
    look at the wire would recognize the command class
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .dfi_packet import DRAMCommand

# ---------------------------------------------------------------------
# CA1[2:0] command codes (JESD209-2 Table)
# ---------------------------------------------------------------------

_CA1_NOP_DESEL    = 0b111
_CA1_MRW          = 0b000
_CA1_MRR          = 0b001
_CA1_REFRESH      = 0b110   # shared with PRE; CA1[6] = 1 → REF, 0 → PRE
_CA1_PRECHARGE    = 0b110
_CA1_ACTIVATE     = 0b011
_CA1_WRITE        = 0b100
_CA1_READ         = 0b101

# Continuation marker on second cycle for commands that span 2 CAs.
_CA2_CONT         = 0b010


# Bit positions inside CA1 (for shared 0b110 command class).
# Layout chosen so PRE's bank field doesn't clobber the REF flag bit.
_CA1_REF_FLAG_BIT       = 6   # set on REF, clear on PRE
_CA1_PREA_ALLBANKS_BIT  = 3   # PRE: 0 = bank-precise, 1 = all-banks
_CA1_PRE_BANK_SHIFT     = 7   # PRE bank in CA1[9:7]
_CA1_REFAB_BIT          = 8   # REF: 0 = per-bank, 1 = all-banks

# Auto-precharge bit (RD/WR commands).
_CA1_RDWR_AP_BIT        = 9


# ---------------------------------------------------------------------
# Encoded CA word — small wrapper for type clarity
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class LPDDR2CA:
    """A 20-bit packed CA word: low 10 bits are CA1, high 10 bits are CA2."""

    word: int

    @property
    def ca1(self) -> int:
        return self.word & 0x3FF

    @property
    def ca2(self) -> int:
        return (self.word >> 10) & 0x3FF


# ---------------------------------------------------------------------
# Public encoders
# ---------------------------------------------------------------------


def encode_lpddr2_ca(
    cmd: DRAMCommand,
    *,
    bank: int = 0,
    row: int = 0,
    col: int = 0,
    auto_precharge: bool = False,
    all_banks: bool = False,
    mr_addr: int = 0,
    mr_data: int = 0,
) -> int:
    """Pack a high-level command + args into the 20-bit dfi_address word.

    Returns an int with bits[9:0] = CA cycle 1, bits[19:10] = CA cycle 2.
    The caller assigns this directly to ``dfi_address``.

    Raises ``ValueError`` for commands LPDDR2/3 doesn't define on the CA
    bus (e.g., SRE/SRX which use CKE/CS sequences, not CA codes).
    """
    if cmd == DRAMCommand.NOP or cmd == DRAMCommand.DESEL:
        ca1 = _CA1_NOP_DESEL
        ca2 = _CA1_NOP_DESEL
    elif cmd == DRAMCommand.ACT:
        # CA1[2:0]=011, [5:3]=bank, [9:6]=row_hi[3:0]
        # CA2[2:0]=010, [9:3]=row_lo[6:0]
        ca1 = (
            _CA1_ACTIVATE
            | ((bank & 0x7) << 3)
            | (((row >> 7) & 0xF) << 6)
        )
        ca2 = _CA2_CONT | ((row & 0x7F) << 3)
    elif cmd in (DRAMCommand.RD, DRAMCommand.RDA):
        # CA1[2:0]=101, [5:3]=bank, [8:6]=col_hi[2:0], [9]=AP
        # CA2[2:0]=010, [9:3]=col_lo[6:0]
        ap = 1 if (auto_precharge or cmd == DRAMCommand.RDA) else 0
        ca1 = (
            _CA1_READ
            | ((bank & 0x7) << 3)
            | (((col >> 7) & 0x7) << 6)
            | (ap << _CA1_RDWR_AP_BIT)
        )
        ca2 = _CA2_CONT | ((col & 0x7F) << 3)
    elif cmd in (DRAMCommand.WR, DRAMCommand.WRA):
        ap = 1 if (auto_precharge or cmd == DRAMCommand.WRA) else 0
        ca1 = (
            _CA1_WRITE
            | ((bank & 0x7) << 3)
            | (((col >> 7) & 0x7) << 6)
            | (ap << _CA1_RDWR_AP_BIT)
        )
        ca2 = _CA2_CONT | ((col & 0x7F) << 3)
    elif cmd in (DRAMCommand.PRE, DRAMCommand.PREA):
        ab = 1 if (all_banks or cmd == DRAMCommand.PREA) else 0
        ca1 = (
            _CA1_PRECHARGE
            | (ab << _CA1_PREA_ALLBANKS_BIT)
            | ((bank & 0x7) << _CA1_PRE_BANK_SHIFT)
            # CA1[6] = 0 distinguishes from REF
        )
        ca2 = _CA1_NOP_DESEL   # single-cycle command; second slot idle
    elif cmd == DRAMCommand.REF:
        ca1 = (
            _CA1_REFRESH
            | (1 << _CA1_REF_FLAG_BIT)      # mark as REF
            | (1 << _CA1_REFAB_BIT)         # all-bank refresh by default
        )
        ca2 = _CA1_NOP_DESEL
    elif cmd == DRAMCommand.MRS:
        # MRW: CA1[2:0]=000, [9:3]=mr_addr[6:0]
        # CA2[2:0]=010, [9:3]=mr_data[6:0]
        ca1 = _CA1_MRW | ((mr_addr & 0x7F) << 3)
        ca2 = _CA2_CONT | ((mr_data & 0x7F) << 3)
    else:
        raise ValueError(
            f"LPDDR2/3 CA bus has no direct encoding for {cmd.name}; "
            "self-refresh / power-down use CKE+CS sequences, not CA codes."
        )

    return (ca1 & 0x3FF) | ((ca2 & 0x3FF) << 10)


# ---------------------------------------------------------------------
# Public decoder
# ---------------------------------------------------------------------


def decode_lpddr2_ca(address: int) -> Tuple[DRAMCommand, dict]:
    """Decode a 20-bit dfi_address word back into (command, args).

    Args dict carries the fields the decoder could recover; keys are
    only populated for commands that use them (bank/row/col/etc.).
    Unknown CA1 command codes decode to NOP.
    """
    ca1 = address & 0x3FF
    cmd_code = ca1 & 0x7

    if cmd_code == _CA1_NOP_DESEL:
        return DRAMCommand.NOP, {}

    ca2 = (address >> 10) & 0x3FF

    if cmd_code == _CA1_ACTIVATE:
        bank   = (ca1 >> 3) & 0x7
        row_hi = (ca1 >> 6) & 0xF
        row_lo = (ca2 >> 3) & 0x7F
        return DRAMCommand.ACT, {
            "bank": bank,
            "row": (row_hi << 7) | row_lo,
        }
    if cmd_code in (_CA1_READ, _CA1_WRITE):
        bank   = (ca1 >> 3) & 0x7
        col_hi = (ca1 >> 6) & 0x7
        col_lo = (ca2 >> 3) & 0x7F
        col = (col_hi << 7) | col_lo
        ap  = bool((ca1 >> _CA1_RDWR_AP_BIT) & 1)
        if cmd_code == _CA1_READ:
            cmd = DRAMCommand.RDA if ap else DRAMCommand.RD
        else:
            cmd = DRAMCommand.WRA if ap else DRAMCommand.WR
        return cmd, {
            "bank": bank, "col": col, "auto_precharge": ap,
        }
    if cmd_code == _CA1_REFRESH:
        # PRE and REF share the 0b110 cmd code; CA1[6] distinguishes
        is_ref = bool((ca1 >> _CA1_REF_FLAG_BIT) & 1)
        if is_ref:
            all_b = bool((ca1 >> _CA1_REFAB_BIT) & 1)
            return DRAMCommand.REF, {"all_banks": all_b}
        all_b = bool((ca1 >> _CA1_PREA_ALLBANKS_BIT) & 1)
        bank  = (ca1 >> _CA1_PRE_BANK_SHIFT) & 0x7
        cmd = DRAMCommand.PREA if all_b else DRAMCommand.PRE
        return cmd, {"bank": bank, "all_banks": all_b}
    if cmd_code == _CA1_MRW:
        mr_addr = (ca1 >> 3) & 0x7F
        mr_data = (ca2 >> 3) & 0x7F
        return DRAMCommand.MRS, {
            "mr_addr": mr_addr, "mr_data": mr_data,
        }
    if cmd_code == _CA1_MRR:
        mr_addr = (ca1 >> 3) & 0x7F
        return DRAMCommand.MRS, {"mr_addr": mr_addr, "is_mrr": True}

    return DRAMCommand.NOP, {}
