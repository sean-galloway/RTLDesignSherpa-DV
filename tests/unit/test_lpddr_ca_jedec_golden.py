# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Independent JESD209-2F Table 60 conformance for the LPDDR2 CA encoder.

The production encoder (``lpddr_ca.py``) and the pumice RTL command formatter
BOTH encode against the same ``LPDDR2_CA_ENCODING.md`` transcription, so a test
that only checks "encoder == RTL" is circular. LiteDRAM cannot break the loop —
it has no LPDDR2 support (only SDR / DDR2/3/4 / LPDDR4/5), and LPDDR4/5 use a
different CA scheme.

This module breaks the loop with a SECOND, independently-structured transcription
of *Table 60 — Command Truth Table* (JESD209-2F, p149-150), read directly from
the JEDEC PDF. It is a per-CA-pin data map (a different code shape than the
imperative encoder), driving a generic packer. If the two independent
transcriptions of the same JEDEC table agree bit-for-bit across a command matrix,
the CA bit-scrambling (which JEDEC §2.14.1 forbids getting wrong) is faithful.

Reference — Table 60 rising / falling CA-pin assignment (CA0..CA9 each edge):

    MRW   r: 0 0 0 0 MA0 MA1 MA2 MA3 MA4 MA5    f: MA6 MA7 OP0..OP7
    ACT   r: 0 1 R8 R9 R10 R11 R12 BA0 BA1 BA2  f: R0..R7 R13 R14
    WRITE r: 1 0 0 . . C1 C2 BA0 BA1 BA2        f: AP C3..C11
    READ  r: 1 0 1 . . C1 C2 BA0 BA1 BA2        f: AP C3..C11
    PRE   r: 1 1 0 1 AB . . BA0 BA1 BA2         f: (don't care)
    REF   r: 0 0 1 AB . . . . . .               f: (don't care)
    NOP   r: 1 1 1 . . . . . . .                f: (don't care)

('.' = RFU / X = don't care -> excluded from the compare mask.) Column bit C0 is
not transmitted (Table 60 NOTE 12).
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.lpddr_ca import (
    encode_lpddr2_ca,
    decode_lpddr2_ca,
)

# Per-CA-pin spec. Each of the 10 entries per edge is one of:
#   int 0/1        -> fixed opcode / RFU-driven-low bit
#   None           -> don't care (X); excluded from the compare mask
#   "AP" / "AB"    -> auto_precharge / all_banks flag bit
#   (field, bit)   -> bit `bit` of arg `field`
_X = None
TABLE60 = {
    "MRW": (
        [0, 0, 0, 0, ("mr_addr", 0), ("mr_addr", 1), ("mr_addr", 2),
         ("mr_addr", 3), ("mr_addr", 4), ("mr_addr", 5)],
        [("mr_addr", 6), ("mr_addr", 7), ("mr_data", 0), ("mr_data", 1),
         ("mr_data", 2), ("mr_data", 3), ("mr_data", 4), ("mr_data", 5),
         ("mr_data", 6), ("mr_data", 7)],
    ),
    "ACT": (
        [0, 1, ("row", 8), ("row", 9), ("row", 10), ("row", 11), ("row", 12),
         ("bank", 0), ("bank", 1), ("bank", 2)],
        [("row", 0), ("row", 1), ("row", 2), ("row", 3), ("row", 4),
         ("row", 5), ("row", 6), ("row", 7), ("row", 13), ("row", 14)],
    ),
    "WR": (
        [1, 0, 0, 0, 0, ("col", 1), ("col", 2), ("bank", 0), ("bank", 1),
         ("bank", 2)],
        ["AP", ("col", 3), ("col", 4), ("col", 5), ("col", 6), ("col", 7),
         ("col", 8), ("col", 9), ("col", 10), ("col", 11)],
    ),
    "RD": (
        [1, 0, 1, 0, 0, ("col", 1), ("col", 2), ("bank", 0), ("bank", 1),
         ("bank", 2)],
        ["AP", ("col", 3), ("col", 4), ("col", 5), ("col", 6), ("col", 7),
         ("col", 8), ("col", 9), ("col", 10), ("col", 11)],
    ),
    "PRE": (
        [1, 1, 0, 1, "AB", _X, _X, ("bank", 0), ("bank", 1), ("bank", 2)],
        [_X] * 10,
    ),
    "REF": (
        [0, 0, 1, "AB", _X, _X, _X, _X, _X, _X],
        [_X] * 10,
    ),
    "NOP": (
        [1, 1, 1, _X, _X, _X, _X, _X, _X, _X],
        [_X] * 10,
    ),
}


def _pin_value(spec, args) -> int:
    if spec == "AP":
        return 1 if args.get("auto_precharge") else 0
    if spec == "AB":
        return 1 if args.get("all_banks") else 0
    field, bit = spec
    return (args.get(field, 0) >> bit) & 1


def _ref_encode(key: str, **args) -> tuple[int, int]:
    """Return (word, care_mask) from the independent Table 60 pin map."""
    rspec, fspec = TABLE60[key]
    word = care = 0
    for edge, spec_list in ((0, rspec), (10, fspec)):
        for i, spec in enumerate(spec_list):
            if spec is None:
                continue
            care |= 1 << (edge + i)
            v = spec if isinstance(spec, int) else _pin_value(spec, args)
            word |= (v & 1) << (edge + i)
    return word, care


# command matrix: (spec-key, DRAMCommand emitted by the encoder, kwargs)
_MATRIX = [
    ("MRW", DRAMCommand.MRS, dict(mr_addr=0x2A, mr_data=0x55)),
    ("MRW", DRAMCommand.MRS, dict(mr_addr=0xFF, mr_data=0xAA)),
    ("ACT", DRAMCommand.ACT, dict(bank=5, row=0x7FFF)),
    ("ACT", DRAMCommand.ACT, dict(bank=2, row=0x1234)),
    ("RD",  DRAMCommand.RD,  dict(bank=3, col=0x2AA)),
    ("RD",  DRAMCommand.RDA, dict(bank=3, col=0x154, auto_precharge=True)),
    ("WR",  DRAMCommand.WR,  dict(bank=6, col=0x2AA)),
    ("WR",  DRAMCommand.WRA, dict(bank=6, col=0x154, auto_precharge=True)),
    ("PRE", DRAMCommand.PRE,  dict(bank=4)),
    ("PRE", DRAMCommand.PREA, dict(all_banks=True)),
    ("REF", DRAMCommand.REF,  dict(all_banks=True)),
    ("REF", DRAMCommand.REF,  dict(all_banks=False)),
    ("NOP", DRAMCommand.NOP,  dict()),
]


@pytest.mark.parametrize("key,cmd,kwargs", _MATRIX,
                         ids=[f"{k}-{c.name}" for k, c, _ in _MATRIX])
def test_encoder_matches_independent_table60(key, cmd, kwargs):
    """encode_lpddr2_ca must agree bit-for-bit (on defined pins) with the
    independent Table 60 pin map."""
    ref_word, care = _ref_encode(key, **kwargs)
    got = encode_lpddr2_ca(cmd, **kwargs)
    assert (got & care) == (ref_word & care), (
        f"{cmd.name}: encoder {got:#07x} vs Table60 ref {ref_word:#07x} "
        f"(care mask {care:#07x}); diff on pins "
        f"{((got ^ ref_word) & care):#07x}"
    )


@pytest.mark.parametrize("key,cmd,kwargs", _MATRIX,
                         ids=[f"{k}-{c.name}" for k, c, _ in _MATRIX])
def test_decoder_inverts_independent_table60(key, cmd, kwargs):
    """decode_lpddr2_ca must recover the command + fields from a word built by
    the independent reference (C0 is not transmitted, so odd columns lose bit 0)."""
    ref_word, _ = _ref_encode(key, **kwargs)
    got_cmd, args = decode_lpddr2_ca(ref_word)

    if cmd in (DRAMCommand.PREA,):
        assert got_cmd == DRAMCommand.PREA
        assert args["all_banks"] is True
        return
    if cmd == DRAMCommand.NOP:
        assert got_cmd == DRAMCommand.NOP
        return

    assert got_cmd == cmd, f"decoded {got_cmd.name}, expected {cmd.name}"
    if "bank" in kwargs and cmd not in (DRAMCommand.REF,):
        assert args["bank"] == kwargs["bank"]
    if "row" in kwargs:
        assert args["row"] == kwargs["row"]
    if "col" in kwargs:
        assert args["col"] == (kwargs["col"] & ~1)   # C0 not transmitted
    if "mr_addr" in kwargs:
        assert args["mr_addr"] == kwargs["mr_addr"]
    if "mr_data" in kwargs:
        assert args["mr_data"] == kwargs["mr_data"]
    if cmd == DRAMCommand.REF:
        assert args["all_banks"] is kwargs["all_banks"]
