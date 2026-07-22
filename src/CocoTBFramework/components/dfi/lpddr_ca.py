# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""LPDDR2 CA-bus command encoding for the DFI BFM — bit-exact JESD209-2F.

LPDDR2 replaces the DDR-style separate ``dfi_ras_n``/``dfi_cas_n``/``dfi_we_n``/
``dfi_bank`` control with a 10-bit multiplexed Command/Address (CA) bus carried
across TWO clock edges (rising = CA*r, falling = CA*f). Per DFI v2.1.1 the two CA
cycles are carried together on ``dfi_address`` as one 20-bit word per command:

    dfi_address[i]      = CA{i} on the rising  edge   (i = 0..9)
    dfi_address[10 + i] = CA{i} on the falling edge   (i = 0..9)

The command AND a *scrambled* row/column address are packed per JESD209-2F
**Table 60 (Command Truth Table, p149-150)**. JEDEC forbids any other bit ordering
(§2.14.1), so this encoding is a spec requirement, not a BFM convenience.

SINGLE SOURCE OF TRUTH — this module and the RTL command formatter
(``pumice-ddr2-lpddr2/rtl/fub/dfi_cmd_formatter.sv`` LPDDR2 branch) BOTH encode
against ``pumice-ddr2-lpddr2/rtl/LPDDR2_CA_ENCODING.md`` (the transcription of
Table 60). The RTL formatter's output is decoded here in the conformance test
(``dv/tests/fub/test_dfi_cmd_formatter.py``), so any drift fails immediately.

Command decode (rising-edge opcode bits):

    CA0r CA1r CA2r CA3r   command
      0    0    0    0    MRW  (Mode Register Write)
      0    0    0    1    MRR  (Mode Register Read)
      0    0    1    0    REF  per-bank   (8-bank parts only)
      0    0    1    1    REF  all-bank
      0    1    -    -    ACTIVATE
      1    0    0    -    WRITE   (WRA when AP=CA0f set)
      1    0    1    -    READ    (RDA when AP=CA0f set)
      1    1    0    1    PRECHARGE (PREA when AB=CA4r set)
      1    1    0    0    BST  (burst terminate; decodes to NOP here — unused)
      1    1    1    -    NOP / Deselect

Power-down / self-refresh entry & exit are CKE+CS sequences (Table 61), NOT CA
opcodes — ``encode_lpddr2_ca`` raises ``ValueError`` for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .dfi_packet import DRAMCommand

# ---------------------------------------------------------------------
# Encoded CA word — small wrapper for type clarity
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class LPDDR2CA:
    """A 20-bit packed CA word: low 10 bits = rising edge, high 10 = falling."""

    word: int

    @property
    def rising(self) -> int:
        return self.word & 0x3FF

    @property
    def falling(self) -> int:
        return (self.word >> 10) & 0x3FF


# ---------------------------------------------------------------------
# Public encoder
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
    """Pack a high-level command + args into the 20-bit ``dfi_address`` word.

    Returns an int with bits[9:0] = rising-edge CA (CA0..CA9), bits[19:10] =
    falling-edge CA. The caller assigns this directly to ``dfi_address``. Layout
    is bit-exact JESD209-2F Table 60 (see module docstring / LPDDR2_CA_ENCODING.md).

    ``col`` bit 0 (C0) is implied 0 and not transmitted (Table 60 NOTE 12).
    Raises ``ValueError`` for commands LPDDR2 does not define on the CA bus.
    """
    r = 0   # rising-edge  CA0..CA9 -> bit 0..9
    f = 0   # falling-edge CA0..CA9 -> bit 0..9

    def rb(ca: int, v: int) -> None:
        nonlocal r
        r |= (v & 1) << ca

    def fb(ca: int, v: int) -> None:
        nonlocal f
        f |= (v & 1) << ca

    if cmd in (DRAMCommand.NOP, DRAMCommand.DESEL):
        # CA0r=CA1r=CA2r=CA3r = H
        for ca in range(4):
            rb(ca, 1)

    elif cmd == DRAMCommand.ACT:
        # opcode CA0r=0, CA1r=1 ; bank CA7r..CA9r
        rb(1, 1)
        for i in range(3):
            rb(7 + i, bank >> i)
        # row hi R8..R12 -> CA2r..CA6r
        for i in range(5):
            rb(2 + i, row >> (8 + i))
        # row lo R0..R7 -> CA0f..CA7f ; R13 -> CA8f ; R14 -> CA9f
        for i in range(8):
            fb(i, row >> i)
        fb(8, row >> 13)
        fb(9, row >> 14)

    elif cmd in (DRAMCommand.RD, DRAMCommand.RDA, DRAMCommand.WR, DRAMCommand.WRA):
        is_read = cmd in (DRAMCommand.RD, DRAMCommand.RDA)
        ap = 1 if (auto_precharge or cmd in (DRAMCommand.RDA, DRAMCommand.WRA)) else 0
        # opcode CA0r=1, CA1r=0, CA2r = 1(read)/0(write)
        rb(0, 1)
        rb(2, 1 if is_read else 0)
        # bank CA7r..CA9r
        for i in range(3):
            rb(7 + i, bank >> i)
        # C1,C2 -> CA5r,CA6r  (C0 implied 0)
        rb(5, col >> 1)
        rb(6, col >> 2)
        # AP -> CA0f ; C3..C11 -> CA1f..CA9f
        fb(0, ap)
        for i in range(9):
            fb(1 + i, col >> (3 + i))

    elif cmd in (DRAMCommand.PRE, DRAMCommand.PREA):
        ab = 1 if (all_banks or cmd == DRAMCommand.PREA) else 0
        # opcode CA0r=1, CA1r=1, CA2r=0, CA3r=1 ; AB -> CA4r ; bank CA7r..CA9r
        rb(0, 1)
        rb(1, 1)
        rb(3, 1)
        rb(4, ab)
        for i in range(3):
            rb(7 + i, bank >> i)
        # falling edge all don't-care (0)

    elif cmd == DRAMCommand.REF:
        # opcode CA0r=0, CA1r=0, CA2r=1 ; CA3r = 1(all-bank)/0(per-bank)
        rb(2, 1)
        rb(3, 1 if all_banks else 0)

    elif cmd == DRAMCommand.MRS:
        # MRW: opcode CA0r..CA3r=0 ; MA0..MA5 -> CA4r..CA9r
        for i in range(6):
            rb(4 + i, mr_addr >> i)
        # MA6,MA7 -> CA0f,CA1f ; OP0..OP7 -> CA2f..CA9f
        fb(0, mr_addr >> 6)
        fb(1, mr_addr >> 7)
        for i in range(8):
            fb(2 + i, mr_data >> i)

    else:
        raise ValueError(
            f"LPDDR2 CA bus has no direct encoding for {cmd.name}; "
            "self-refresh / power-down use CKE+CS sequences, not CA codes."
        )

    return (r & 0x3FF) | ((f & 0x3FF) << 10)


# ---------------------------------------------------------------------
# Public decoder
# ---------------------------------------------------------------------


def decode_lpddr2_ca(address: int) -> Tuple[DRAMCommand, dict]:
    """Decode a 20-bit ``dfi_address`` word back into (command, args).

    Inverse of :func:`encode_lpddr2_ca`, bit-exact per Table 60. Args dict carries
    only the fields a given command uses. Unknown opcodes and BST decode to NOP.
    """
    r = address & 0x3FF
    f = (address >> 10) & 0x3FF

    def rbit(ca: int) -> int:
        return (r >> ca) & 1

    def fbit(ca: int) -> int:
        return (f >> ca) & 1

    c0, c1, c2, c3 = rbit(0), rbit(1), rbit(2), rbit(3)

    # ----- MRW / MRR / REF : CA0r=0, CA1r=0 -----
    if c0 == 0 and c1 == 0:
        if c2 == 0:
            mr_addr = (
                rbit(4) | (rbit(5) << 1) | (rbit(6) << 2) | (rbit(7) << 3)
                | (rbit(8) << 4) | (rbit(9) << 5) | (fbit(0) << 6) | (fbit(1) << 7)
            )
            if c3 == 0:   # MRW
                mr_data = (
                    fbit(2) | (fbit(3) << 1) | (fbit(4) << 2) | (fbit(5) << 3)
                    | (fbit(6) << 4) | (fbit(7) << 5) | (fbit(8) << 6) | (fbit(9) << 7)
                )
                return DRAMCommand.MRS, {"mr_addr": mr_addr, "mr_data": mr_data}
            # MRR
            return DRAMCommand.MRS, {"mr_addr": mr_addr, "is_mrr": True}
        # REF (CA2r=1); CA3r = all-bank vs per-bank
        return DRAMCommand.REF, {"all_banks": bool(c3)}

    # ----- ACTIVATE : CA0r=0, CA1r=1 -----
    if c0 == 0 and c1 == 1:
        bank = rbit(7) | (rbit(8) << 1) | (rbit(9) << 2)
        row = (
            (rbit(2) << 8) | (rbit(3) << 9) | (rbit(4) << 10)
            | (rbit(5) << 11) | (rbit(6) << 12)
        )
        for i in range(8):
            row |= fbit(i) << i
        row |= (fbit(8) << 13) | (fbit(9) << 14)
        return DRAMCommand.ACT, {"bank": bank, "row": row}

    # ----- READ / WRITE : CA0r=1, CA1r=0 -----
    if c0 == 1 and c1 == 0:
        bank = rbit(7) | (rbit(8) << 1) | (rbit(9) << 2)
        col = (rbit(5) << 1) | (rbit(6) << 2)          # C1,C2 (C0 implied 0)
        col |= (
            (fbit(1) << 3) | (fbit(2) << 4) | (fbit(3) << 5) | (fbit(4) << 6)
            | (fbit(5) << 7) | (fbit(6) << 8) | (fbit(7) << 9) | (fbit(8) << 10)
            | (fbit(9) << 11)
        )
        ap = bool(fbit(0))
        if c2 == 1:   # READ
            cmd = DRAMCommand.RDA if ap else DRAMCommand.RD
        else:         # WRITE
            cmd = DRAMCommand.WRA if ap else DRAMCommand.WR
        return cmd, {"bank": bank, "col": col, "auto_precharge": ap}

    # ----- CA0r=1, CA1r=1 : PRECHARGE / BST / NOP -----
    if c2 == 1:
        return DRAMCommand.NOP, {}          # CA2r=1 -> NOP/Deselect
    if c3 == 1:                             # CA2r=0, CA3r=1 -> PRECHARGE
        ab = bool(rbit(4))
        bank = rbit(7) | (rbit(8) << 1) | (rbit(9) << 2)
        cmd = DRAMCommand.PREA if ab else DRAMCommand.PRE
        return cmd, {"bank": bank, "all_banks": ab}
    # CA2r=0, CA3r=0 -> BST (unused): treat as NOP
    return DRAMCommand.NOP, {}
