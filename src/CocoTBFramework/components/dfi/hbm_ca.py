"""HBM4 dfi_cmdaddr packing for DFI v6.0.

Spec grounding: DDR PHY Interface Specification v6.0 (May 8, 2026),
section 3.1.2.4 "For HBM4" and Table 22 "Bit Definitions of the
dfi_cmdaddr bus for HBM4 Command Mode".

For HBM4 the CA bus carries **two independent DDR commands** per
dfi_cmdaddr word: a 10-bit Row command interface, an 8-bit Column
command interface, and 1 reserved bit (ARFU) that is included in
parity calculations. The rising-edge Row/Column/ARFU concatenate on
the lower 19 bits and the falling-edge set on the upper 19 bits:

    bits [ 9: 0]  Row     (rising edge)
    bits [17:10]  Column  (rising edge)
    bit  [18]     ARFU    (rising edge)
    bits [28:19]  Row     (falling edge)
    bits [36:29]  Column  (falling edge)
    bit  [37]     ARFU    (falling edge)

Scope note: DFI defines only this TRANSPORT mapping. The Row/Column
command *opcodes* (which 10-bit row pattern means ACTIVATE, etc.) are
defined by the HBM4 DRAM standard (JESD270-4), which is not part of
the DFI collateral — callers supply raw command values. When the DRAM
spec lands in the specs area, an opcode layer can sit on top of this
module without changing the packing.
"""

from typing import NamedTuple

# Table 22 geometry
HBM4_ROW_WIDTH = 10
HBM4_COL_WIDTH = 8
HBM4_ARFU_WIDTH = 1
HBM4_EDGE_WIDTH = HBM4_ROW_WIDTH + HBM4_COL_WIDTH + HBM4_ARFU_WIDTH  # 19
HBM4_CMDADDR_WIDTH = 2 * HBM4_EDGE_WIDTH                             # 38

_ROW_MASK = (1 << HBM4_ROW_WIDTH) - 1
_COL_MASK = (1 << HBM4_COL_WIDTH) - 1
_EDGE_MASK = (1 << HBM4_EDGE_WIDTH) - 1

_COL_SHIFT = HBM4_ROW_WIDTH                       # 10
_ARFU_SHIFT = HBM4_ROW_WIDTH + HBM4_COL_WIDTH     # 18


class HBM4CAEdge(NamedTuple):
    """One edge's worth of HBM4 CA content."""
    row: int = 0
    col: int = 0
    arfu: int = 0


class HBM4CAWord(NamedTuple):
    """A full dfi_cmdaddr word for HBM4 command mode."""
    rise: HBM4CAEdge
    fall: HBM4CAEdge


def pack_hbm4_edge(row: int, col: int, arfu: int = 0) -> int:
    """Pack one edge's Row/Column/ARFU into its 19-bit lane."""
    if not 0 <= row <= _ROW_MASK:
        raise ValueError(f"row 0x{row:X} exceeds {HBM4_ROW_WIDTH} bits")
    if not 0 <= col <= _COL_MASK:
        raise ValueError(f"col 0x{col:X} exceeds {HBM4_COL_WIDTH} bits")
    if arfu not in (0, 1):
        raise ValueError(f"arfu must be 0 or 1, got {arfu}")
    return (arfu << _ARFU_SHIFT) | (col << _COL_SHIFT) | row


def unpack_hbm4_edge(edge_bits: int) -> HBM4CAEdge:
    """Unpack one 19-bit edge lane."""
    return HBM4CAEdge(
        row=edge_bits & _ROW_MASK,
        col=(edge_bits >> _COL_SHIFT) & _COL_MASK,
        arfu=(edge_bits >> _ARFU_SHIFT) & 1,
    )


def pack_hbm4_cmdaddr(rise: HBM4CAEdge, fall: HBM4CAEdge) -> int:
    """Pack both edges into the 38-bit dfi_cmdaddr value (Table 22)."""
    lo = pack_hbm4_edge(*rise)
    hi = pack_hbm4_edge(*fall)
    return (hi << HBM4_EDGE_WIDTH) | lo


def unpack_hbm4_cmdaddr(value: int) -> HBM4CAWord:
    """Split a 38-bit dfi_cmdaddr value into its two edges."""
    if not 0 <= value < (1 << HBM4_CMDADDR_WIDTH):
        raise ValueError(
            f"cmdaddr 0x{value:X} exceeds {HBM4_CMDADDR_WIDTH} bits")
    return HBM4CAWord(
        rise=unpack_hbm4_edge(value & _EDGE_MASK),
        fall=unpack_hbm4_edge(value >> HBM4_EDGE_WIDTH),
    )
