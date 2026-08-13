"""DDR5 CA command map — JESD79-5B Table 31 (Command Truth Table).

The DDR5 CA bus is 14-bit SDR; bit ``i`` of an edge value is CA``i``.
Commands are 1-cycle (CA1=H) or 2-cycle (CA1=L) — Table 31 note (b);
each engine "edge" is one CA cycle. CS_n framing (first cycle L,
second cycle H) is transport-level and not part of the CA values.

Modeling decisions, all anchored to Table 31 and its notes:

* ``V`` (valid H-or-L) and ``X`` bits encode as 0 and are ignored on
  decode, matching the HBM4 reference maps.
* WR/WRA, RD/RDA, WRP/WRPA are distinct commands split by the
  cycle-2 CA10 auto-precharge bit (``AP=L`` in the table) — this is
  what the engine's multi-edge opcode support exists for.
* REF vs RFM split on CA9 per note 23's MR58 OP[0]=1 semantics
  (REF requires CA9=H, RFM drives CA9=L). With OP[0]=0 the DRAM
  "will treat a RFM command as a REF command", so decoding a
  CA9=L refresh as the RFM flavor matches device behavior either way.
* ``rir`` (refresh-interval-rate, CA8, note 24) and ``odt`` (PDE
  CA11, note 16) are 1-bit fields carrying the raw pin level.
* ``wr_partial`` (cycle-2 CA11, note 12): pin level; L = partial
  write. ``bl`` (CA5, note 15): pin level; L selects the MR0[1:0]
  alternate burst mode, H the default BL16.
* ACT's row field is 18 bits (R0-R3 on cycle 1, R4-R17 on cycle 2);
  cycle-2 CA13 is the R17/CID3 multi-mode pin (note 17), modeled as
  row bit 17 — 3DS parts using CID3 there should mask it themselves.
  ACT ``cid`` is therefore 3 bits; the column commands carry 4
  (CID0-2 on cycle 1 CA11-13, CID3 on cycle 2 CA13, note 19).
* Column addresses are spec-faithful per command: ``col`` is
  C[10:2] (9 bits) for RD/RDA but C[10:3] (8 bits) for WR/WRA and
  WRP/WRPA — writes are BL16-aligned so C2 is not transmitted.
* DES is CS_n=H with CA don't-care — no CA pattern, so no map entry.
  RFU rows are omitted. NOP and PDX share the all-high pattern
  (power-down state selects the meaning): ``pdx`` is an alias.
"""

from typing import Tuple

from .ca_map import BitRun, CAMap, CommandSpec, FieldSpec, OpcodeBit

DDR5_CA_WIDTH = 14


def _op(*bits: Tuple[int, int, int]) -> Tuple[OpcodeBit, ...]:
    return tuple(OpcodeBit(*b) for b in bits)


# Every 1-cycle command opens with CA0=H CA1=H; 2-cycle with CA1=L.
_ONE = ((0, 0, 1), (0, 1, 1))

_BA = FieldSpec("ba", 2, (BitRun(0, 6, 0, 2),))
_BG = FieldSpec("bg", 3, (BitRun(0, 8, 0, 3),))
_BL = FieldSpec("bl", 1, (BitRun(0, 5, 0, 1),))
_RIR = FieldSpec("rir", 1, (BitRun(0, 8, 0, 1),))
# 1-cycle commands: CID0-2 on CA11-13, CID3 on CA5.
_CID_1CYC = FieldSpec("cid", 4, (BitRun(0, 11, 0, 3), BitRun(0, 5, 3, 1)))
# 2-cycle commands: CID0-2 on cycle-1 CA11-13, CID3 on cycle-2 CA13.
_CID_2CYC = FieldSpec("cid", 4, (BitRun(0, 11, 0, 3), BitRun(1, 13, 3, 1)))
_COL_WR = FieldSpec("col", 8, (BitRun(1, 1, 0, 8),))   # C3..C10
_COL_RD = FieldSpec("col", 9, (BitRun(1, 0, 0, 9),))   # C2..C10
_WR_PARTIAL = FieldSpec("wr_partial", 1, (BitRun(1, 11, 0, 1),))


def _wr_fields() -> Tuple[FieldSpec, ...]:
    return (_BL, _BA, _BG, _CID_2CYC, _COL_WR, _WR_PARTIAL)


def _rd_fields() -> Tuple[FieldSpec, ...]:
    return (_BL, _BA, _BG, _CID_2CYC, _COL_RD)


DDR5_CA_MAP = CAMap(
    name="ddr5",
    bus_width=DDR5_CA_WIDTH,
    commands=(
        # -- two-cycle (CA1=L) ------------------------------------------
        CommandSpec("act", 2, _op((0, 0, 0), (0, 1, 0)), fields=(
            FieldSpec("row", 18, (
                BitRun(0, 2, 0, 4),      # R0..R3, cycle 1 CA2..CA5
                BitRun(1, 0, 4, 14))),   # R4..R17, cycle 2 CA0..CA13
            _BA, _BG,
            FieldSpec("cid", 3, (BitRun(0, 11, 0, 3),)),
        )),
        CommandSpec("wrp", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 0), (0, 3, 1), (0, 4, 0),
            (0, 5, 1), (1, 10, 1), (1, 11, 1)),
            fields=(_BA, _BG, _CID_2CYC, _COL_WR)),
        CommandSpec("wrpa", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 0), (0, 3, 1), (0, 4, 0),
            (0, 5, 1), (1, 10, 0), (1, 11, 1)),
            fields=(_BA, _BG, _CID_2CYC, _COL_WR)),
        CommandSpec("mrw", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 0), (0, 4, 0)),
            fields=(
                FieldSpec("mra", 8, (BitRun(0, 5, 0, 8),)),
                FieldSpec("op", 8, (BitRun(1, 0, 0, 8),)),
                FieldSpec("cw", 1, (BitRun(1, 10, 0, 1),)),
            )),
        CommandSpec("mrr", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 0), (0, 4, 1),
            (1, 0, 0), (1, 1, 0)),   # note 21: cycle-2 CA[1:0]=LL
            fields=(
                FieldSpec("mra", 8, (BitRun(0, 5, 0, 8),)),
                FieldSpec("cw", 1, (BitRun(1, 10, 0, 1),)),
            )),
        CommandSpec("wr", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 1), (0, 4, 0),
            (1, 10, 1)),
            fields=_wr_fields()),
        CommandSpec("wra", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 1), (0, 4, 0),
            (1, 10, 0)),
            fields=_wr_fields()),
        CommandSpec("rd", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 1), (0, 4, 1),
            (1, 10, 1)),
            fields=_rd_fields()),
        CommandSpec("rda", 2, _op(
            (0, 0, 1), (0, 1, 0), (0, 2, 1), (0, 3, 1), (0, 4, 1),
            (1, 10, 0)),
            fields=_rd_fields()),
        # -- one-cycle (CA0=H CA1=H) --------------------------------------
        CommandSpec("vrefca", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 0), (0, 12, 0)),
            fields=(FieldSpec("op", 7, (BitRun(0, 5, 0, 7),)),)),
        CommandSpec("vrefcs", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 0), (0, 12, 1)),
            fields=(FieldSpec("op", 7, (BitRun(0, 5, 0, 7),)),)),
        CommandSpec("refab", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 1), (0, 9, 1),
            (0, 10, 0)),
            fields=(_CID_1CYC, _RIR)),
        CommandSpec("rfmab", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 1), (0, 9, 0),
            (0, 10, 0)),
            fields=(_CID_1CYC,)),
        CommandSpec("refsb", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 1), (0, 9, 1),
            (0, 10, 1)),
            fields=(_BA, _CID_1CYC, _RIR)),
        CommandSpec("rfmsb", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 0), (0, 4, 1), (0, 9, 0),
            (0, 10, 1)),
            fields=(_BA, _CID_1CYC)),
        CommandSpec("preab", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 1), (0, 4, 0), (0, 10, 0)),
            fields=(_CID_1CYC,)),
        CommandSpec("presb", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 1), (0, 4, 0), (0, 10, 1)),
            fields=(_BA, _CID_1CYC)),
        CommandSpec("prepb", 1, _op(
            *_ONE, (0, 2, 0), (0, 3, 1), (0, 4, 1)),
            fields=(_BA, _BG, _CID_1CYC)),
        CommandSpec("sre", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 0), (0, 4, 1), (0, 9, 1),
            (0, 10, 0))),
        CommandSpec("sref", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 0), (0, 4, 1), (0, 9, 0),
            (0, 10, 0))),
        CommandSpec("pde", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 0), (0, 4, 1), (0, 10, 1)),
            fields=(FieldSpec("odt", 1, (BitRun(0, 11, 0, 1),)),)),
        CommandSpec("mpc", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 1), (0, 4, 0)),
            fields=(FieldSpec("op", 8, (BitRun(0, 5, 0, 8),)),)),
        CommandSpec("nop", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 1), (0, 4, 1))),
        CommandSpec("pdx", 1, _op(
            *_ONE, (0, 2, 1), (0, 3, 1), (0, 4, 1)),
            alias_of="nop"),
    ),
)
