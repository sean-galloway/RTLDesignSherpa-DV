"""LPDDR6 CA command map — JESD209-6 Table 254 (Command Truth Table).

LPDDR6 commands are **two** clock cycles long on a 4-bit DDR CA bus:
CS is sampled at both rising edges (R1, R2) and CA[3:0] at all four
edges R1/F1/R2/F2 — note 1. Every command here is therefore
``n_edges=4`` (edge 0=R1, 1=F1, 2=R2, 3=F2) and bit ``i`` of an edge
value is CA``i``. Each *clock* of the pair packs into one
``dfi_cmdaddr`` word via :func:`ca_transport.pack_ddr_cmdaddr` with
``LPDDR6_CA_WIDTH`` (DFI v6.0 Table 16), so one command occupies two
consecutive cmdaddr words. This is the DDR command-mode encoding;
v6.0 Table 17 SDR command mode is a transport variant.

Unlike LPDDR5, bank organization is fixed: BG[1:0] + BA[1:0] on F2
for every banked command (note 3).

Modeling decisions, all anchored to Table 254 and its notes:

* ``V``/``X`` bits encode as 0 and are ignored on decode. Note 17's
  CA parity operand (PAR) rides bits the table marks ``V/PAR`` on
  R1 CA3; parity is a mode-gated overlay (MR2 OP[0] and MR26 OP[2]),
  so those bits stay unconstrained here rather than being modeled as
  a field the encoder would have to compute.
* DES (CS=L, CA don't-care) and PDX-NT (note 15 — every CA bit is
  ``V``/``X``, the command is distinguished purely by CS framing)
  have no CA pattern and so have no map entry. Note 13's NT-ODT
  rank targeting — CS de-asserted at R2 for non-target ranks on
  WR-S/WR-L/WFF — is likewise CS framing, not CA content.
* ACT-1 and ACT-2 are separate commands (note 4): ``act1`` carries
  ``row_hi`` = R[16:11] (field bit 0 = R11), ``act2`` carries
  ``row_lo`` = R[10:0].
* REF carries the dual-bank second target (note 11) as ``dbg``, and
  its ``rfm`` bit (F1 CA2) selects refresh management. ``ab``
  (note 5) makes it all-banks.
* ``col`` is C[5:0] for WR-S/RD-S/RD-L, but C[5:1] for WR-L (field
  bit 0 = C1) — the BL48 write does not transmit C0.
* Pin-level operand fields carry raw levels: ``sc`` (sub-channel
  select, note 12), ``ap`` (note 6), ``ab`` (note 5), ``ws`` /
  ``ws_off`` (WCK2CK sync, notes 7/10/18), ``bc`` (MRW broadcast,
  note 19), ``pd`` (SRE, note 8).
* The RFU row (R1 = L H H) is omitted.
"""

from typing import Tuple

from .ca_map import BitRun, CAMap, CommandSpec, FieldSpec, OpcodeBit

LPDDR6_CA_WIDTH = 4

R1, F1, R2, F2 = 0, 1, 2, 3


def _op(*bits: Tuple[int, int, int]) -> Tuple[OpcodeBit, ...]:
    return tuple(OpcodeBit(*b) for b in bits)


# Banked commands put BA[1:0] on F2 CA[1:0] and BG[1:0] on F2 CA[3:2].
_BANKS = (FieldSpec("ba", 2, (BitRun(F2, 0, 0, 2),)),
          FieldSpec("bg", 2, (BitRun(F2, 2, 0, 2),)))
_SC = FieldSpec("sc", 1, (BitRun(F1, 3, 0, 1),))
_AP = FieldSpec("ap", 1, (BitRun(F1, 2, 0, 1),))
_WS = FieldSpec("ws", 1, (BitRun(R1, 3, 0, 1),))
# C0-C1 on F1 CA[1:0], C2-C5 on R2 CA[3:0].
_COL6 = FieldSpec("col", 6, (BitRun(F1, 0, 0, 2), BitRun(R2, 0, 2, 4)))
# WR-L transmits no C0; field bit 0 is C1.
_COL5 = FieldSpec("col", 5, (BitRun(F1, 1, 0, 1), BitRun(R2, 0, 1, 4)))
# MA0-3 / OP0-3 on F2, MA4-7 / OP4-7 on R2.
_MA8 = FieldSpec("ma", 8, (BitRun(F2, 0, 0, 4), BitRun(R2, 0, 4, 4)))
_OP8 = FieldSpec("op", 8, (BitRun(F2, 0, 0, 4), BitRun(R2, 0, 4, 4)))

# Every command's R1 opcode falls in one of these CA[2:0] groups.
_R1_LLL = ((R1, 0, 0), (R1, 1, 0), (R1, 2, 0))
_R1_HLL = ((R1, 0, 1), (R1, 1, 0), (R1, 2, 0))
_R1_HHH = ((R1, 0, 1), (R1, 1, 1), (R1, 2, 1))


LPDDR6_CA_MAP = CAMap(
    name="lpddr6",
    bus_width=LPDDR6_CA_WIDTH,
    commands=(
        # -- R1 = L L L ---------------------------------------------------
        CommandSpec("nop", 4, _op(
            *_R1_LLL, (F1, 0, 0), (F1, 1, 0), (F1, 2, 0))),
        CommandSpec("pde", 4, _op(
            *_R1_LLL, (F1, 0, 0), (F1, 1, 1), (F1, 2, 0))),
        CommandSpec("sre", 4, _op(
            *_R1_LLL, (F1, 0, 0), (F1, 1, 0), (F1, 2, 1)),
            fields=(FieldSpec("pd", 1, (BitRun(F1, 3, 0, 1),)),)),
        CommandSpec("srx", 4, _op(
            *_R1_LLL, (F1, 0, 0), (F1, 1, 1), (F1, 2, 1))),
        CommandSpec("pre", 4, _op(
            *_R1_LLL, (F1, 0, 1), (F1, 1, 1)),
            fields=_BANKS + (
                _SC, FieldSpec("ab", 1, (BitRun(R2, 3, 0, 1),)))),
        CommandSpec("ref", 4, _op(
            *_R1_LLL, (F1, 0, 1), (F1, 1, 0)),
            fields=_BANKS + (
                _SC,
                FieldSpec("rfm", 1, (BitRun(F1, 2, 0, 1),)),
                FieldSpec("dbg", 2, (BitRun(R2, 0, 0, 2),)),
                FieldSpec("ab", 1, (BitRun(R2, 3, 0, 1),)))),
        # -- R1 = H H H (activate pair) -----------------------------------
        CommandSpec("act1", 4, _op(*_R1_HHH, (F1, 0, 1)),
                    fields=_BANKS + (
                        _SC,
                        FieldSpec("row_hi", 6, (BitRun(R2, 0, 0, 4),
                                                BitRun(F1, 1, 4, 2))))),
        CommandSpec("act2", 4, _op(*_R1_HHH, (F1, 0, 0)),
                    fields=(FieldSpec("row_lo", 11, (
                        BitRun(F2, 0, 0, 4),
                        BitRun(R2, 0, 4, 4),
                        BitRun(F1, 1, 8, 3))),)),
        # -- column commands ----------------------------------------------
        CommandSpec("wr_s", 4, _op(
            (R1, 0, 1), (R1, 1, 0), (R1, 2, 1)),
            fields=_BANKS + (_WS, _COL6, _AP, _SC)),
        CommandSpec("wr_l", 4, _op(
            (R1, 0, 0), (R1, 1, 0), (R1, 2, 1), (F1, 0, 0)),
            fields=_BANKS + (_WS, _COL5, _AP, _SC)),
        CommandSpec("rd_s", 4, _op(
            (R1, 0, 1), (R1, 1, 1), (R1, 2, 0)),
            fields=_BANKS + (_WS, _COL6, _AP, _SC)),
        CommandSpec("rd_l", 4, _op(
            (R1, 0, 0), (R1, 1, 1), (R1, 2, 0)),
            fields=_BANKS + (_WS, _COL6, _AP, _SC)),
        # -- R1 = H L L ---------------------------------------------------
        CommandSpec("cas", 4, _op(
            *_R1_HLL, (F1, 0, 1), (F1, 1, 1), (F1, 2, 1)),
            fields=(_WS,
                    FieldSpec("ws_off", 1, (BitRun(F1, 3, 0, 1),)))),
        CommandSpec("mrr", 4, _op(
            *_R1_HLL, (F1, 0, 0), (F1, 1, 1), (F1, 2, 1)),
            fields=(_WS, _SC, _MA8)),
        CommandSpec("mpc", 4, _op(
            *_R1_HLL, (F1, 0, 1), (F1, 1, 0), (F1, 2, 1)),
            fields=(_OP8,)),
        CommandSpec("mrw1", 4, _op(
            *_R1_HLL, (F1, 0, 0), (F1, 1, 0), (F1, 2, 1)),
            fields=(_MA8,
                    FieldSpec("bc", 1, (BitRun(F1, 3, 0, 1),)))),
        CommandSpec("mrw2", 4, _op(
            *_R1_HLL, (F1, 0, 1), (F1, 1, 1), (F1, 2, 0)),
            fields=(_OP8,)),
        CommandSpec("wff", 4, _op(
            *_R1_HLL, (F1, 0, 0), (F1, 1, 1), (F1, 2, 0)),
            fields=(_WS,)),
        CommandSpec("rff", 4, _op(
            *_R1_HLL, (F1, 0, 1), (F1, 1, 0), (F1, 2, 0)),
            fields=(_WS,)),
        CommandSpec("rdc", 4, _op(
            *_R1_HLL, (F1, 0, 0), (F1, 1, 0), (F1, 2, 0)),
            fields=(_WS,)),
    ),
)
