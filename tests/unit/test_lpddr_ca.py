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


@pytest.mark.parametrize("bank,col,ap", [
    (0, 0,        False),
    (7, 0x3FF,    False),
    (4, 0x55,     True),
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
    (7, 0x3FF,    True),
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
    word = encode_lpddr2_ca(DRAMCommand.REF)
    cmd, args = decode_lpddr2_ca(word)
    assert cmd == DRAMCommand.REF
    assert args["all_banks"] is True


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
    """ACTIVATE command class is CA1[2:0]=0b011 per JESD209-2."""
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=0, row=0)
    assert (word & 0x7) == 0b011


def test_read_cmd_code_in_ca1():
    word = encode_lpddr2_ca(DRAMCommand.RD, bank=0, col=0)
    assert (word & 0x7) == 0b101


def test_write_cmd_code_in_ca1():
    word = encode_lpddr2_ca(DRAMCommand.WR, bank=0, col=0)
    assert (word & 0x7) == 0b100


def test_pre_ref_share_cmd_code():
    """PRE and REF share CA1[2:0]=0b110; CA1[6] discriminates."""
    pre_word = encode_lpddr2_ca(DRAMCommand.PRE, bank=0)
    ref_word = encode_lpddr2_ca(DRAMCommand.REF)
    assert (pre_word & 0x7) == 0b110
    assert (ref_word & 0x7) == 0b110
    # CA1[6] = REF flag bit
    assert ((pre_word >> 6) & 1) == 0   # PRE: REF flag clear
    assert ((ref_word >> 6) & 1) == 1   # REF: REF flag set


def test_mrw_cmd_code_in_ca1():
    word = encode_lpddr2_ca(DRAMCommand.MRS, mr_addr=0, mr_data=0)
    assert (word & 0x7) == 0b000


def test_ca2_continuation_marker():
    """Multi-cycle commands use CA2[2:0]=0b010 (continuation)."""
    word = encode_lpddr2_ca(DRAMCommand.ACT, bank=0, row=1)
    ca2 = (word >> 10) & 0x3FF
    assert (ca2 & 0x7) == 0b010


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
