"""LPDDR4 CA command map — JESD209-4E Table 175 (Command Truth Table).

LPDDR4 uses a 6-bit SDR CA bus. Every command except Deselect is two clock
cycles long; bit ``i`` of an edge value is CA``i``, and edge 0 / edge 1 are
the first / second rising-edge samples (R1 / R2).

Modeling decisions, all anchored to Table 175 and its notes:

* ``V`` (valid H-or-L) and ``X`` bits encode as 0 and are ignored on decode,
  matching the other shipped maps.
* Deselect (DES) is defined by CS=L with CA don't-care — it has no CA-only
  pattern, so it is intentionally absent from the map (same treatment as
  DDR5/LPDDR5 DES).
* Power-down entry/exit are CKE+CS sequences, not CA opcodes, so they are
  also absent.
* NOP is encoded as an MPC command with OP6=0 (note 9); MPC training uses
  OP6=1. The two are distinct map entries.
* ACTIVATE is modeled as one four-edge command spanning the ACT-1 / ACT-2
  pair, because the two halves are not distinguishable by their R1 CA bits
  alone (the DRAM resolves them by sequence). The row field is the full
  R0-R18 address.
* RD-1, WR-1, MWR-1 and MRR-1 are modeled as the read/write/MRS commands;
  the CAS-2 companion is a separate ``cas`` entry that carries the column.
  The state-model dispatcher maps ``cas`` to NOP.
* MRW is split into ``mrw1`` (MA0-5 + OP7) and ``mrw2`` (OP0-6); the
  dispatcher pairs them and reconstructs the 8-bit OP value.
* REF carries the ``ab`` and ``rfm`` operands; the dispatcher maps all
  refresh/RFM variants to DRAMCommand.REF.
* C[1:0] are not transmitted on the CA bus (note 8); the ``col`` field is
  C2-C8 and the least significant burst address bits are implied zero.
"""

from typing import Tuple

from .ca_map import BitRun, CAMap, CommandSpec, FieldSpec, OpcodeBit

LPDDR4_CA_WIDTH = 6

R1, R2 = 0, 1


def _op(*bits: Tuple[int, int, int]) -> Tuple[OpcodeBit, ...]:
    return tuple(OpcodeBit(*b) for b in bits)


# Bank address rides ACT-1 R2 CA[2:0].
_BA = FieldSpec("ba", 3, (BitRun(R2, 0, 0, 3),))

# Auto-precharge bit on RD-1 / WR-1 / MWR-1 R2 CA5.
_AP = FieldSpec("ap", 1, (BitRun(R2, 5, 0, 1),))

# Burst-length select on RD-1 / WR-1 R1 CA5.
_BL = FieldSpec("bl", 1, (BitRun(R1, 5, 0, 1),))

# Column C9 on RD-1 / WR-1 / MWR-1 R2 CA4.
_C9 = FieldSpec("c9", 1, (BitRun(R2, 4, 0, 1),))

# CAS-2 column: C2-C7 on R2 CA[5:0], C8 on R1 CA5.
_COL = FieldSpec("col", 7, (BitRun(R2, 0, 0, 6), BitRun(R1, 5, 6, 1)))

# MRW-1: MA0-5 on R2 CA[5:0], OP7 on R1 CA5.
_MA6 = FieldSpec("ma", 6, (BitRun(R2, 0, 0, 6),))
_OP7 = FieldSpec("op7", 1, (BitRun(R1, 5, 0, 1),))

# MRW-2 / MPC operand: OP0-OP5 on R2 CA[5:0], OP6 on R1 CA5.
_OP7LO = FieldSpec("op", 7, (BitRun(R2, 0, 0, 6), BitRun(R1, 5, 6, 1)))

# REF / RFM operands: AB on R1 CA5, RFM on R2 CA3.
_AB = FieldSpec("ab", 1, (BitRun(R1, 5, 0, 1),))
_RFM = FieldSpec("rfm", 1, (BitRun(R2, 3, 0, 1),))


LPDDR4_CA_MAP = CAMap(
    name="lpddr4",
    bus_width=LPDDR4_CA_WIDTH,
    commands=(
        # -- four-edge ACTIVATE pair --------------------------------------
        CommandSpec("act", 4, _op(
            (0, 0, 1), (0, 1, 0),   # ACT-1 R1: CA0=H, CA1=L
        ), fields=(_BA, FieldSpec("row", 19, (
            BitRun(3, 0, 0, 1),   # R0  ACT-2 R2 CA0
            BitRun(3, 1, 1, 1),   # R1  ACT-2 R2 CA1
            BitRun(3, 2, 2, 1),   # R2  ACT-2 R2 CA2
            BitRun(3, 3, 3, 1),   # R3  ACT-2 R2 CA3
            BitRun(3, 4, 4, 1),   # R4  ACT-2 R2 CA4
            BitRun(3, 5, 5, 1),   # R5  ACT-2 R2 CA5
            BitRun(2, 2, 6, 1),   # R6  ACT-2 R1 CA2
            BitRun(2, 3, 7, 1),   # R7  ACT-2 R1 CA3
            BitRun(2, 4, 8, 1),   # R8  ACT-2 R1 CA4
            BitRun(2, 5, 9, 1),   # R9  ACT-2 R1 CA5
            BitRun(1, 4, 10, 1),  # R10 ACT-1 R2 CA4
            BitRun(1, 5, 11, 1),  # R11 ACT-1 R2 CA5
            BitRun(0, 2, 12, 1),  # R12 ACT-1 R1 CA2
            BitRun(0, 3, 13, 1),  # R13 ACT-1 R1 CA3
            BitRun(0, 4, 14, 1),  # R14 ACT-1 R1 CA4
            BitRun(0, 5, 15, 1),  # R15 ACT-1 R1 CA5
            BitRun(1, 3, 16, 1),  # R16 ACT-1 R2 CA3
            BitRun(2, 0, 17, 1),  # R17 ACT-2 R1 CA0
            BitRun(2, 1, 18, 1),  # R18 ACT-2 R1 CA1
        )),)),
        # -- two-edge commands ---------------------------------------------
        # NOP is MPC with OP6=0.
        CommandSpec("nop", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0), (R1, 4, 0),
            (R1, 5, 0))),
        # MPC training: OP6=1, OP0-OP5 on R2.
        CommandSpec("mpc", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0), (R1, 4, 0),
            (R1, 5, 1)),
            fields=(_OP7LO,)),
        # Precharge: AB flag plus bank.
        CommandSpec("pre", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0), (R1, 4, 1)),
            fields=(_BA, _AB,)),
        # Refresh: AB and RFM flags plus bank.
        CommandSpec("ref", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1), (R1, 4, 0)),
            fields=(_BA, _AB, _RFM)),
        # Self refresh entry / exit.
        CommandSpec("sre", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1), (R1, 4, 1))),
        CommandSpec("srx", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (R1, 3, 0), (R1, 4, 1))),
        # Read / write / masked write -1.
        CommandSpec("rd", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 0), (R1, 3, 0), (R1, 4, 0)),
            fields=(_BA, _BL, _C9, _AP)),
        CommandSpec("wr", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (R1, 3, 0), (R1, 4, 0)),
            fields=(_BA, _BL, _C9, _AP)),
        CommandSpec("mwr", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (R1, 3, 1), (R1, 4, 0),
            (R1, 5, 0)),
            fields=(_BA, _C9, _AP)),
        # CAS-2 companion for RD/WR/MWR/MRR/MPC FIFO/cal.
        CommandSpec("cas", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 0), (R1, 3, 0), (R1, 4, 1)),
            fields=(_COL,)),
        # Mode register write: mrw1 (MA + OP7), mrw2 (OP0-6).
        CommandSpec("mrw1", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 1), (R1, 3, 0), (R1, 4, 0)),
            fields=(_MA6, _OP7)),
        CommandSpec("mrw2", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 1), (R1, 3, 0), (R1, 4, 1)),
            fields=(_OP7LO,)),
        # Mode register read.
        CommandSpec("mrr", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 1), (R1, 3, 1), (R1, 4, 0)),
            fields=(_MA6,)),
    ),
)
