# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Round-trip tests for LPDDR2/3 CA bus encoder/decoder."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.lpddr_ca import (
    encode_lpddr2_ca,
    decode_lpddr2_ca,
)


# ---------------------------------------------------------------------
# Round-trip: encode → decode preserves command + args
# ---------------------------------------------------------------------


def test_nop_roundtrips():
    word = encode_lpddr2_ca(DRAMCommand.NOP)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.NOP


def test_act_roundtrips_low_row():
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=3, row=0x42)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.ACT
    assert args["bank"] == 3
    assert args["row"] == 0x42


def test_act_roundtrips_high_row():
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=5, row=0x7FF)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.ACT
    assert args["bank"] == 5
    assert args["row"] == 0x7FF   # 11 bits fully covered


# NOTE: LPDDR2 does not transmit column bit C0 (Table 60 NOTE 12 — it is implied
# 0), so round-trip test vectors must use EVEN columns; an odd column loses its
# LSB by design (0x3FF -> 0x3FE). 0x3FE still exercises C1..C9.
@pytest.mark.parametrize("bank,col,ap", [
    (0, 0,        False),
    (7, 0x3FE,    False),
    (4, 0x54,     True),
    (1, 0x100,    False),
])
def test_read_roundtrips(bank, col, ap):
    word = encode_lpddr2_ca(
        DRAMCommand.RD, bank=bank, col=col, auto_precharge=ap,
    )
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == (DRAMCommand.RDA if ap else DRAMCommand.RD)
    assert args["bank"] == bank
    assert args["col"] == col
    assert args["auto_precharge"] == ap


@pytest.mark.parametrize("bank,col,ap", [
    (0, 0,        False),
    (7, 0x3FE,    True),    # even col: C0 not transmitted (Table 60 NOTE 12)
    (3, 0x40,     False),
])
def test_write_roundtrips(bank, col, ap):
    word = encode_lpddr2_ca(
        DRAMCommand.WR, bank=bank, col=col, auto_precharge=ap,
    )
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == (DRAMCommand.WRA if ap else DRAMCommand.WR)
    assert args["bank"] == bank
    assert args["col"] == col


def test_precharge_bank_roundtrips():
    word = encode_lpddr2_ca(DRAMCommand.PRE, bank=6, all_banks=False)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.PRE
    assert args["bank"] == 6
    assert args["all_banks"] is False


def test_precharge_all_roundtrips():
    word = encode_lpddr2_ca(DRAMCommand.PREA, bank=0, all_banks=True)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.PREA
    assert args["all_banks"] is True


def test_refresh_roundtrips():
    # all-bank refresh is CA3r=H (per-bank = CA3r=L, the encoder default).
    word = encode_lpddr2_ca(DRAMCommand.REF, all_banks=True)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.REF
    assert args["all_banks"] is True


def test_refresh_per_bank_roundtrips():
    word = encode_lpddr2_ca(DRAMCommand.REF, all_banks=False)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.REF
    assert args["all_banks"] is False


def test_mrs_roundtrips():
    word = encode_lpddr2_ca(DRAMCommand.MRS, mr_addr=0x12, mr_data=0x34)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.MRS
    assert args["mr_addr"] == 0x12
    assert args["mr_data"] == 0x34


# ---------------------------------------------------------------------
# Encoding properties: CA1[2:0] matches the spec's command class codes
# ---------------------------------------------------------------------


def test_act_cmd_code_in_ca1():
    """ACTIVATE is {CA0r,CA1r,CA2r} = L,H,- per JESD209-2F Table 60. With CA0r
    in bit 0, that packs to (word & 0x7) == 0b010."""
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=0, row=0)
    assert (word & 0x7) == 0b010


def test_read_cmd_code_in_ca1():
    word = encode_lpddr2_ca(DRAMCommand.RD, bank=0, col=0)
    assert (word & 0x7) == 0b101


def test_write_cmd_code_in_ca1():
    """WRITE is {CA0r,CA1r,CA2r} = H,L,L per Table 60 -> (word & 0x7) == 0b001
    (READ is H,L,H == 0b101; CA2r discriminates)."""
    word = encode_lpddr2_ca(DRAMCommand.WR, bank=0, col=0)
    assert (word & 0x7) == 0b001


def test_pre_and_ref_cmd_codes():
    """PRE and REF have DISTINCT opcodes per Table 60 (they do not share a
    class): PRE = {CA0r,CA1r,CA2r}=H,H,L == 0b011; REF = L,L,H == 0b100. The
    all-bank flag is CA3r for REF and CA4r (AB) for PRE."""
    pre_word = encode_lpddr2_ca(DRAMCommand.PRE, bank=0)
    ref_all  = encode_lpddr2_ca(DRAMCommand.REF, all_banks=True)
    ref_per  = encode_lpddr2_ca(DRAMCommand.REF, all_banks=False)
    assert (pre_word & 0x7) == 0b011
    assert (ref_all  & 0x7) == 0b100
    assert (ref_per  & 0x7) == 0b100
    # REF all-bank vs per-bank is CA3r.
    assert ((ref_all >> 3) & 1) == 1
    assert ((ref_per >> 3) & 1) == 0


def test_mrw_cmd_code_in_ca1():
    word = encode_lpddr2_ca(DRAMCommand.MRS, mr_addr=0, mr_data=0)
    assert (word & 0x7) == 0b000


def test_act_second_cycle_carries_row_lsbs():
    """LPDDR2 has no 'continuation marker' — the 2nd (falling-edge) CA cycle
    carries address payload, not an opcode. For ACTIVATE it holds row bits
    R0..R7 in CA0f..CA7f (Table 60)."""
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=0, row=0b10101101)
    falling = (word >> 10) & 0x3FF
    assert (falling & 0xFF) == 0b10101101   # R0..R7


# ---------------------------------------------------------------------
# Coverage gap: commands we explicitly reject
# ---------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [
    DRAMCommand.SRE,
    DRAMCommand.SRX,
    DRAMCommand.PDE,
    DRAMCommand.PDX,
])
def test_power_commands_rejected(cmd):
    with pytest.raises(ValueError, match="CA bus"):
        encode_lpddr2_ca(cmd)


# ---------------------------------------------------------------------
# Word width: must fit in 20 bits
# ---------------------------------------------------------------------


@pytest.mark.parametrize("cmd_args", [
    (DRAMCommand.ACT,  {"bank": 7, "row": 0x7FF}),
    (DRAMCommand.RDA,  {"bank": 7, "col": 0x3FF}),
    (DRAMCommand.WRA,  {"bank": 7, "col": 0x3FF}),
    (DRAMCommand.PREA, {"all_banks": True}),
    (DRAMCommand.REF,  {}),
    (DRAMCommand.MRS,  {"mr_addr": 0x7F, "mr_data": 0x7F}),
])
def test_word_fits_in_20_bits(cmd_args):
    cmd, kwargs = cmd_args
    word = encode_lpddr2_ca(cmd, **kwargs)
    assert 0 <= word < (1 << 20), (
        f"encoding of {cmd.name} produced {word:#x} which exceeds 20 bits"
    )
