"""HBM4 Row/Column command encode/decode (JESD270-4A).

Spec grounding: JEDEC Standard No. 270-4A, section 6.3.1 "Command
Truth Tables" — Table 33 (Row Commands) and Table 34 (Column
Commands). This is the opcode layer on top of the DFI v6.0 transport
packing in :mod:`hbm_ca` (which owns the dfi_cmdaddr bit lanes).

Bus conventions here: an edge value is an integer whose bit *i* is
signal R*i* (row bus, 10 bits) or C*i* (column bus, 8 bits). H=1,
L=0. "V" (valid, don't-care) bits encode as 0 and are ignored by
decode.

Command shapes (Table 33/34):

* Row bus: most commands occupy ONE edge; ACT occupies three edges
  (R, F, then the next rising edge) carrying RA[14:0]; PDE and SRE
  occupy a full cycle (R and F edges with the same opcode).
* Column bus: CNOP is one rising edge; RD/RDA/WR/WRA/MRS occupy a
  full cycle (R edge = opcode + high fields, F edge = remaining
  address/operand bits).

Decode aliasing, per the spec:

* RNOP and PDX/SRX share the all-high pattern (R0-R3 = H H H H);
  which one it *means* depends on power-down/self-refresh state
  (Table 33 note 8). Decode returns ``RowCommand.RNOP``.
* REFab vs RFMab share R0-R2 = H H L; the discriminator is R8
  (L = REFab, H = RFMab).
"""

from enum import Enum
from typing import List, NamedTuple, Optional, Tuple


class RowCommand(str, Enum):
    RNOP = "rnop"          # also PDX/SRX by state (note 8)
    ACT = "act"
    PREPB = "prepb"
    PREAB = "preab"
    REFPB = "refpb"
    REFAB = "refab"
    RFMPB = "rfmpb"
    RFMAB = "rfmab"
    PDE = "pde"
    SRE = "sre"


class ColumnCommand(str, Enum):
    CNOP = "cnop"
    RD = "rd"
    RDA = "rda"
    WR = "wr"
    WRA = "wra"
    MRS = "mrs"


ROW_ADDR_WIDTH = 15    # RA[14:0] across the three ACT edges
COL_ADDR_WIDTH = 5     # CA[4:0] on the column F edge
BANK_WIDTH = 4         # BA[3:0]
SID_WIDTH = 2          # SID[1:0] (stack ID; acts as bank bits, note 6)


def _bits(*pairs: Tuple[int, int]) -> int:
    """OR together (bit_position, value) pairs (value 0/1 masked)."""
    v = 0
    for pos, val in pairs:
        v |= (val & 1) << pos
    return v


def _field(value: int, width: int, name: str) -> int:
    if not 0 <= value < (1 << width):
        raise ValueError(f"{name} 0x{value:X} exceeds {width} bits")
    return value


# ---------------------------------------------------------------------------
# Row command encoders — each returns the ordered list of edge values.
# ---------------------------------------------------------------------------

def encode_row_nop() -> List[int]:
    """RNOP: R0-R3 = H (one edge)."""
    return [0b0000001111]


def encode_row_act(pc: int, sid: int, ba: int, row: int) -> List[int]:
    """ACT (Table 33): three edges — R, F, next R.

    edge0 (R): L H H PC SID0 SID1 BA0..BA3
    edge1 (F): H H RA8..RA14 DRFM(=0 here)
    edge2 (R): H H RA0..RA7
    """
    _field(pc, 1, "pc")
    _field(sid, SID_WIDTH, "sid")
    _field(ba, BANK_WIDTH, "ba")
    _field(row, ROW_ADDR_WIDTH, "row")
    e0 = _bits((0, 0), (1, 1), (2, 1), (3, pc),
               (4, sid), (5, sid >> 1),
               (6, ba), (7, ba >> 1), (8, ba >> 2), (9, ba >> 3))
    e1 = _bits((0, 1), (1, 1)) | (((row >> 8) & 0x7F) << 2)   # RA8..RA14
    e2 = _bits((0, 1), (1, 1)) | ((row & 0xFF) << 2)          # RA0..RA7
    return [e0, e1, e2]


def _encode_row_banked(op_bits: Tuple[int, int, int], pc: int, sid: int,
                       ba: int) -> List[int]:
    _field(pc, 1, "pc")
    _field(sid, SID_WIDTH, "sid")
    _field(ba, BANK_WIDTH, "ba")
    r0, r1, r2 = op_bits
    return [_bits((0, r0), (1, r1), (2, r2), (3, pc),
                  (4, sid), (5, sid >> 1),
                  (6, ba), (7, ba >> 1), (8, ba >> 2), (9, ba >> 3))]


def encode_row_prepb(pc: int, sid: int, ba: int) -> List[int]:
    """PREpb: H L L PC SID BA (one edge)."""
    return _encode_row_banked((1, 0, 0), pc, sid, ba)


def encode_row_preab(pc: int) -> List[int]:
    """PREab: H L H PC (one edge)."""
    _field(pc, 1, "pc")
    return [_bits((0, 1), (1, 0), (2, 1), (3, pc))]


def encode_row_refpb(pc: int, sid: int, ba: int) -> List[int]:
    """REFpb: L L L PC SID BA (one edge)."""
    return _encode_row_banked((0, 0, 0), pc, sid, ba)


def encode_row_refab(pc: int) -> List[int]:
    """REFab: H H L PC, R8=L (one edge)."""
    _field(pc, 1, "pc")
    return [_bits((0, 1), (1, 1), (2, 0), (3, pc), (8, 0))]


def encode_row_rfmpb(pc: int, sid: int, ba: int) -> List[int]:
    """RFMpb (DRFMpb): L L H PC SID BA (one edge)."""
    return _encode_row_banked((0, 0, 1), pc, sid, ba)


def encode_row_rfmab(pc: int) -> List[int]:
    """RFMab: H H L PC, R8=H (one edge)."""
    _field(pc, 1, "pc")
    return [_bits((0, 1), (1, 1), (2, 0), (3, pc), (8, 1))]


def encode_row_pde() -> List[int]:
    """PDE: L H L H on both edges of one cycle."""
    e = _bits((0, 0), (1, 1), (2, 0), (3, 1))
    return [e, e]


def encode_row_sre() -> List[int]:
    """SRE: L H L L on both edges of one cycle."""
    e = _bits((0, 0), (1, 1), (2, 0), (3, 0))
    return [e, e]


def encode_row_pdx_srx() -> List[int]:
    """PDX/SRX: all-high opcode (same pattern as RNOP; state selects
    the meaning, Table 33 note 8)."""
    return encode_row_nop()


class RowDecode(NamedTuple):
    command: RowCommand
    pc: Optional[int] = None
    sid: Optional[int] = None
    ba: Optional[int] = None


def decode_row_edge(edge: int) -> RowDecode:
    """Classify one row-bus edge by its Table 33 opcode bits.

    ACT continuation edges (RA transfers) start with R0=H R1=H and are
    indistinguishable from other H,H-prefixed opcodes in isolation —
    callers must track the two follow-on edges after an ACT themselves
    (or use :func:`decode_row_act_sequence`).
    """
    r0, r1, r2, r3 = edge & 1, (edge >> 1) & 1, (edge >> 2) & 1, (edge >> 3) & 1
    pc = r3
    sid = (edge >> 4) & 0x3
    ba = (edge >> 6) & 0xF
    key = (r0, r1, r2)
    if key == (0, 1, 1):
        return RowDecode(RowCommand.ACT, pc=pc, sid=sid, ba=ba)
    if key == (1, 0, 0):
        return RowDecode(RowCommand.PREPB, pc=pc, sid=sid, ba=ba)
    if key == (1, 0, 1):
        return RowDecode(RowCommand.PREAB, pc=pc)
    if key == (0, 0, 0):
        return RowDecode(RowCommand.REFPB, pc=pc, sid=sid, ba=ba)
    if key == (0, 0, 1):
        return RowDecode(RowCommand.RFMPB, pc=pc, sid=sid, ba=ba)
    if key == (1, 1, 0):
        cmd = RowCommand.RFMAB if (edge >> 8) & 1 else RowCommand.REFAB
        return RowDecode(cmd, pc=pc)
    if key == (0, 1, 0):
        return RowDecode(RowCommand.PDE if r3 else RowCommand.SRE)
    # (1,1,1): RNOP (or PDX/SRX by state)
    return RowDecode(RowCommand.RNOP)


def decode_row_act_sequence(edges: List[int]) -> Tuple[RowDecode, int]:
    """Decode a full 3-edge ACT: returns the RowDecode plus RA[14:0]."""
    if len(edges) != 3:
        raise ValueError("ACT occupies exactly 3 edges (R, F, R)")
    head = decode_row_edge(edges[0])
    if head.command is not RowCommand.ACT:
        raise ValueError(f"first edge is {head.command}, not ACT")
    ra_hi = (edges[1] >> 2) & 0x7F      # RA8..RA14
    ra_lo = (edges[2] >> 2) & 0xFF      # RA0..RA7
    return head, (ra_hi << 8) | ra_lo


# ---------------------------------------------------------------------------
# Column command encoders — (rise, fall) pairs.
# ---------------------------------------------------------------------------

def encode_col_nop() -> Tuple[int, int]:
    """CNOP: C0-C2 = H on the rising edge."""
    return (0b00000111, 0)


def _encode_col_rw(c3: int, pc: int, sid: int, ba: int,
                   col: int) -> Tuple[int, int]:
    _field(pc, 1, "pc")
    _field(sid, SID_WIDTH, "sid")
    _field(ba, BANK_WIDTH, "ba")
    _field(col, COL_ADDR_WIDTH, "col")
    rise = _bits((0, 1), (1, 0), (3, c3), (4, pc),
                 (5, sid), (6, sid >> 1), (7, ba))
    fall = _bits((0, ba >> 1), (1, ba >> 2), (2, ba >> 3)) | ((col & 0x1F) << 3)
    return rise, fall


def encode_col_rd(pc: int, sid: int, ba: int, col: int,
                  auto_precharge: bool = False) -> Tuple[int, int]:
    """RD / RDA: H L H {L|H} PC SID BA0 | BA1-3 CA0-4."""
    rise, fall = _encode_col_rw(int(auto_precharge), pc, sid, ba, col)
    return rise | (1 << 2), fall


def encode_col_wr(pc: int, sid: int, ba: int, col: int,
                  auto_precharge: bool = False) -> Tuple[int, int]:
    """WR / WRA: H L L {L|H} PC SID BA0 | BA1-3 CA0-4."""
    return _encode_col_rw(int(auto_precharge), pc, sid, ba, col)


def encode_col_mrs(ma: int, op: int) -> Tuple[int, int]:
    """MRS: L L L MA4 OP5 OP6 OP7 MA0 | MA1-3 OP0-4 (Table 34)."""
    _field(ma, 5, "ma")
    _field(op, 8, "op")
    rise = _bits((3, ma >> 4), (4, op >> 5), (5, op >> 6), (6, op >> 7),
                 (7, ma))
    fall = _bits((0, ma >> 1), (1, ma >> 2), (2, ma >> 3)) | ((op & 0x1F) << 3)
    return rise, fall


class ColumnDecode(NamedTuple):
    command: ColumnCommand
    pc: Optional[int] = None
    sid: Optional[int] = None
    ba: Optional[int] = None
    col: Optional[int] = None
    ma: Optional[int] = None
    op: Optional[int] = None


def decode_col_pair(rise: int, fall: int) -> ColumnDecode:
    """Decode a full-cycle column command from its (rise, fall) pair."""
    c0, c1, c2, c3 = rise & 1, (rise >> 1) & 1, (rise >> 2) & 1, (rise >> 3) & 1
    if (c0, c1, c2) == (1, 1, 1):
        return ColumnDecode(ColumnCommand.CNOP)
    if (c0, c1, c2) == (0, 0, 0):
        ma = (((fall >> 0) & 1) << 1 | ((fall >> 1) & 1) << 2
              | ((fall >> 2) & 1) << 3 | ((rise >> 3) & 1) << 4
              | (rise >> 7) & 1)
        op = (((rise >> 4) & 1) << 5 | ((rise >> 5) & 1) << 6
              | ((rise >> 6) & 1) << 7 | (fall >> 3) & 0x1F)
        return ColumnDecode(ColumnCommand.MRS, ma=ma, op=op)
    if (c0, c1) == (1, 0):
        pc = (rise >> 4) & 1
        sid = (rise >> 5) & 0x3
        ba = ((rise >> 7) & 1) | ((fall & 0x7) << 1)
        col = (fall >> 3) & 0x1F
        if c2:  # read class
            cmd = ColumnCommand.RDA if c3 else ColumnCommand.RD
        else:
            cmd = ColumnCommand.WRA if c3 else ColumnCommand.WR
        return ColumnDecode(cmd, pc=pc, sid=sid, ba=ba, col=col)
    raise ValueError(f"reserved column encoding: rise=0x{rise:02X}")
