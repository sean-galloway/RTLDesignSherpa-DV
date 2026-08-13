"""LPDDR5 CA command map — JESD209-5C Table 201 (Command Truth Table).

LPDDR5 commands are one clock long on a 7-bit DDR CA bus: CS is
sampled at the rising edge (R1) and CA[6:0] at both R1 and the
falling edge (F1) — note 1. So every command here is ``n_edges=2``
with edge 0 = R1 and edge 1 = F1, and bit ``i`` of an edge value is
CA``i``. The DFI transport that carries these two phases in one
``dfi_cmdaddr`` word is :func:`ca_transport.pack_ddr_cmdaddr` with
``LPDDR5_CA_WIDTH`` (DFI v6.0 Table 15).

**Bank organization changes the field layout**, which is why this
module exports a factory rather than one constant. LPDDR5 devices
run in BG mode (BG[1:0] + BA[1:0]), 16B mode (BA[3:0]), or 8B mode
(BA[2:0]) and Table 201 gives a different F1 bank row for each.
:func:`lpddr5_ca_map` builds the map for a given organization;
``LPDDR5_CA_MAP_BG`` / ``_16B`` / ``_8B`` are the prebuilt ones.

Modeling decisions, all anchored to Table 201 and its notes:

* ``V`` (valid H-or-L) and ``X`` bits encode as 0 and are ignored on
  decode, matching the other shipped maps.
* DES is CS=L with CA don't-care — transport-level, no CA pattern,
  so no map entry (same treatment as DDR5 DES).
* PDE additionally requires CS=L at the *next* rising edge (R2,
  note 12); that is CS framing outside the CA values.
* ACT-1 and ACT-2 are separate commands, not two edges of one — up
  to 8 clocks and other commands may sit between them (note 4).
  ``act1`` carries ``row_hi`` = R[17:11] (field bit 0 = R11),
  ``act2`` carries ``row_lo`` = R[10:0].
* REF / RFM / DRFM share an R1 pattern and split on F1: CA3=L is
  REF, CA3=H with CA5=L is RFM, CA3=H with CA5=H is DRFM. Their
  bank fields are narrower than PRE's (CA[2:0] only) because F1
  CA3 is the discriminator; DRFM recovers the top bank bit on CA4.
  DRFM has no 8B row in Table 201, so the 8B map omits it.
* Column addresses are spec-faithful per command: ``col`` is C[5:0]
  for MWR/WR16/RD16/RD32, but C[5:1] for WR32 (field bit 0 = C1) —
  BL32 writes are 32-aligned so C0 is not transmitted. WR32/RD32
  are BG/16B-only (notes 8, 11) and are omitted from the 8B map.
* In 8B mode the READ commands put burst-start bit B4 on F1 CA3
  where other organizations put a bank bit (note 10), so the 8B map
  gives reads a ``b4`` field.
* ``ab`` (PRE/REF/RFM CA6, note 5), ``ap`` (write/read CA6, note 6),
  ``sb0`` (RFM CA4, note 16), ``dsm``/``pd`` (SRE, note 9) and the
  CAS operands (note 7, Table 202) carry raw pin levels; Table 202's
  legal-combination rules are controller policy, not encoding.
* PRE has two MR75-gated address-sample variants that redefine F1
  CA5/CA6. MR75 is device state and not decodable from the CA bus,
  so the base map ships plain ``pre`` and ``pre_mode=`` selects a
  variant instead of making the map ambiguous.
"""

from typing import Tuple

from .ca_map import BitRun, CAMap, CommandSpec, FieldSpec, OpcodeBit

LPDDR5_CA_WIDTH = 7

BANK_ORGS = ("BG", "16B", "8B")
PRE_MODES = ("default", "no_sample", "sample")

R1, F1 = 0, 1


def _op(*bits: Tuple[int, int, int]) -> Tuple[OpcodeBit, ...]:
    return tuple(OpcodeBit(*b) for b in bits)


# -- bank field layouts (F1), per Table 201's BG / 16B / 8B rows ------------

def _banks_full(org: str) -> Tuple[FieldSpec, ...]:
    """PRE / ACT-1 / column commands: bank bits on F1 CA[3:0]."""
    if org == "BG":
        return (FieldSpec("ba", 2, (BitRun(F1, 0, 0, 2),)),
                FieldSpec("bg", 2, (BitRun(F1, 2, 0, 2),)))
    if org == "16B":
        return (FieldSpec("ba", 4, (BitRun(F1, 0, 0, 4),)),)
    return (FieldSpec("ba", 3, (BitRun(F1, 0, 0, 3),)),)


def _banks_short(org: str) -> Tuple[FieldSpec, ...]:
    """REF / RFM: F1 CA3 is the REF-vs-RFM discriminator, so bank
    bits stop at CA2."""
    if org == "BG":
        return (FieldSpec("ba", 2, (BitRun(F1, 0, 0, 2),)),
                FieldSpec("bg", 1, (BitRun(F1, 2, 0, 1),)))
    return (FieldSpec("ba", 3, (BitRun(F1, 0, 0, 3),)),)


def _banks_drfm(org: str) -> Tuple[FieldSpec, ...]:
    """DRFMpb: like REF/RFM but the top bank bit moves to F1 CA4."""
    if org == "BG":
        return (FieldSpec("ba", 2, (BitRun(F1, 0, 0, 2),)),
                FieldSpec("bg", 2, (BitRun(F1, 2, 0, 1),
                                    BitRun(F1, 4, 1, 1))))
    return (FieldSpec("ba", 4, (BitRun(F1, 0, 0, 3),
                                BitRun(F1, 4, 3, 1))),)


_AB = FieldSpec("ab", 1, (BitRun(F1, 6, 0, 1),))
_AP = FieldSpec("ap", 1, (BitRun(F1, 6, 0, 1),))
# C0 on R1 CA3, C1-C2 on F1 CA4-CA5, C3-C5 on R1 CA4-CA6.
_COL6 = FieldSpec("col", 6, (BitRun(R1, 3, 0, 1),
                             BitRun(F1, 4, 1, 2),
                             BitRun(R1, 4, 3, 3)))
# WR32 transmits no C0; field bit 0 is C1.
_COL5 = FieldSpec("col", 5, (BitRun(F1, 4, 0, 2),
                             BitRun(R1, 4, 2, 3)))
# OP0-OP6 on F1 CA[6:0], OP7 on R1 CA6.
_OP8 = FieldSpec("op", 8, (BitRun(F1, 0, 0, 7), BitRun(R1, 6, 7, 1)))
_MA7 = FieldSpec("ma", 7, (BitRun(F1, 0, 0, 7),))


def lpddr5_ca_map(bank_org: str = "16B",
                  *, pre_mode: str = "default") -> CAMap:
    """Build the LPDDR5 CA map for a bank organization.

    ``bank_org`` is one of ``"BG"``, ``"16B"``, ``"8B"``.
    ``pre_mode`` selects the PRECHARGE variant: ``"default"``
    (F1 CA5=V, CA6=AB), ``"no_sample"`` (MR75 OP[2]=1, OP[3]=0:
    F1 CA5=L, CA6=L — note 14) or ``"sample"`` (MR75 OP[2]=1,
    OP[3]=1: F1 CA5=H, CA6=L — note 15).
    """
    if bank_org not in BANK_ORGS:
        raise ValueError(
            f"bank_org must be one of {BANK_ORGS}, got {bank_org!r}")
    if pre_mode not in PRE_MODES:
        raise ValueError(
            f"pre_mode must be one of {PRE_MODES}, got {pre_mode!r}")

    full = _banks_full(bank_org)
    short = _banks_short(bank_org)
    wide_bg = bank_org in ("BG", "16B")   # WR32/RD32/DRFM availability

    if pre_mode == "default":
        pre = CommandSpec("pre", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 1), (R1, 6, 1)),
            fields=full + (_AB,))
    else:
        pre = CommandSpec("pre", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 1), (R1, 6, 1),
            (F1, 5, 1 if pre_mode == "sample" else 0), (F1, 6, 0)),
            fields=full)

    # Read commands: 8B mode puts burst-start B4 where the other
    # organizations put a bank bit (note 10).
    rd_fields = full + (_COL6, _AP)
    if bank_org == "8B":
        rd_fields += (FieldSpec("b4", 1, (BitRun(F1, 3, 0, 1),)),)

    commands = [
        CommandSpec("nop", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 0), (R1, 5, 0), (R1, 6, 0))),
        CommandSpec("pde", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 0), (R1, 5, 0), (R1, 6, 1))),
        CommandSpec("act1", 2, _op(
            (R1, 0, 1), (R1, 1, 1), (R1, 2, 1)),
            fields=full + (
                FieldSpec("row_hi", 7, (BitRun(F1, 4, 0, 3),
                                        BitRun(R1, 3, 3, 4))),)),
        CommandSpec("act2", 2, _op(
            (R1, 0, 1), (R1, 1, 1), (R1, 2, 0)),
            fields=(FieldSpec("row_lo", 11, (BitRun(F1, 0, 0, 7),
                                             BitRun(R1, 3, 7, 4))),)),
        pre,
        CommandSpec("ref", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 1), (R1, 6, 0), (F1, 3, 0)),
            fields=short + (_AB,)),
        CommandSpec("rfm", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 1), (R1, 6, 0),
            (F1, 3, 1), (F1, 5, 0)),
            fields=short + (
                FieldSpec("sb0", 1, (BitRun(F1, 4, 0, 1),)), _AB)),
        CommandSpec("mwr", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 0)),
            fields=full + (_COL6, _AP)),
        CommandSpec("wr16", 2, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 1)),
            fields=full + (_COL6, _AP)),
        CommandSpec("rd16", 2, _op(
            (R1, 0, 1), (R1, 1, 0), (R1, 2, 0)),
            fields=rd_fields),
        CommandSpec("cas", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (R1, 3, 1)),
            fields=(
                FieldSpec("ws_wr", 1, (BitRun(R1, 4, 0, 1),)),
                FieldSpec("ws_rd", 1, (BitRun(R1, 5, 0, 1),)),
                FieldSpec("ws_fs", 1, (BitRun(R1, 6, 0, 1),)),
                FieldSpec("dc", 4, (BitRun(F1, 0, 0, 4),)),
                FieldSpec("wrx", 1, (BitRun(F1, 4, 0, 1),)),
                FieldSpec("wxsa", 1, (BitRun(F1, 5, 0, 1),)),
                FieldSpec("wxsb_b3", 1, (BitRun(F1, 6, 0, 1),)),
            )),
        CommandSpec("mpc", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 1), (R1, 5, 1)),
            fields=(_OP8,)),
        CommandSpec("sre", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 0), (R1, 5, 1), (R1, 6, 1)),
            fields=(
                FieldSpec("dsm", 1, (BitRun(F1, 5, 0, 1),)),
                FieldSpec("pd", 1, (BitRun(F1, 6, 0, 1),)),
            )),
        CommandSpec("srx", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 0), (R1, 5, 1), (R1, 6, 0))),
        CommandSpec("mrw1", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 0), (R1, 6, 1)),
            fields=(_MA7,)),
        CommandSpec("mrw2", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 0), (R1, 5, 0)),
            fields=(_OP8,)),
        CommandSpec("mrr", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
            (R1, 4, 1), (R1, 5, 0), (R1, 6, 0)),
            fields=(_MA7,)),
        CommandSpec("wff", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 0), (R1, 5, 1), (R1, 6, 1))),
        CommandSpec("rff", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 0), (R1, 5, 1), (R1, 6, 0))),
        CommandSpec("rdc", 2, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 0),
            (R1, 4, 1), (R1, 5, 0), (R1, 6, 1))),
    ]

    if wide_bg:
        commands.insert(commands.index(pre) + 1, CommandSpec(
            "drfm", 2, _op(
                (R1, 0, 0), (R1, 1, 0), (R1, 2, 0), (R1, 3, 1),
                (R1, 4, 1), (R1, 5, 1), (R1, 6, 0),
                (F1, 3, 1), (F1, 5, 1), (F1, 6, 0)),
            fields=_banks_drfm(bank_org)))
        commands += [
            CommandSpec("wr32", 2, _op(
                (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (R1, 3, 0)),
                fields=full + (_COL5, _AP)),
            CommandSpec("rd32", 2, _op(
                (R1, 0, 1), (R1, 1, 0), (R1, 2, 1)),
                fields=full + (_COL6, _AP)),
        ]

    return CAMap(f"lpddr5_{bank_org.lower()}", LPDDR5_CA_WIDTH,
                 tuple(commands))


LPDDR5_CA_MAP_BG = lpddr5_ca_map("BG")
LPDDR5_CA_MAP_16B = lpddr5_ca_map("16B")
LPDDR5_CA_MAP_8B = lpddr5_ca_map("8B")
