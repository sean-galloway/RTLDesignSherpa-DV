"""Unit tests for DFISlavePHY's DFI_RATE>1 phase masking — G-01a regression.

Background:
    The DDR2/DDR3 DFI bus carries N phases per cycle bit-packed as
    `{phase_{N-1}, …, phase_0}` for the command signals, the wrdata,
    and the wrdata_mask. A controller running at DFI_RATE=2 drives the
    command on phase 0 and holds phase 1 NOP for typical traffic.

    The original BFM (pre-G-01a) read the bus signals as full integers
    and looked them up against single-bit decode tables — for DFI_RATE=2
    every command silently mapped to NOP and every wrdata beat
    overflowed beat_bytes. These tests pin the masking helpers so the
    regression can't reappear.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.dfi_slave_phy import (
    decode_phase0_cmd,
    slice_phase_wrdata,
)


# ---------------------------------------------------------------------
# decode_phase0_cmd — DFI_RATE=1 (sanity) + DFI_RATE>1 (regression)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("ras,cas,we,cmd", [
    (0, 1, 1, DRAMCommand.ACT),
    (1, 0, 1, DRAMCommand.RD),
    (1, 0, 0, DRAMCommand.WR),
    (0, 1, 0, DRAMCommand.PRE),
    (0, 0, 1, DRAMCommand.REF),
    (0, 0, 0, DRAMCommand.MRS),
    (1, 1, 1, DRAMCommand.NOP),
])
def test_decode_phase0_single_bit(ras, cas, we, cmd):
    """DFI_RATE=1 path — bus values are already 1-bit each."""
    assert decode_phase0_cmd(ras, cas, we) == cmd


def test_decode_phase0_rate2_act():
    """phase 1 NOP (1,1,1) above phase 0 ACT (0,1,1):
    bus = (ras=10, cas=11, we=11) = (2, 3, 3)."""
    assert decode_phase0_cmd(0b10, 0b11, 0b11) == DRAMCommand.ACT


def test_decode_phase0_rate2_rd():
    """phase 1 NOP above phase 0 RD (1,0,1):
    bus = (ras=11, cas=10, we=11) = (3, 2, 3) — the value the BFM
    used to look up (3,2,3) in the single-bit table and get NOP."""
    assert decode_phase0_cmd(0b11, 0b10, 0b11) == DRAMCommand.RD


def test_decode_phase0_rate2_wr():
    """phase 1 NOP above phase 0 WR (1,0,0):
    bus = (ras=11, cas=10, we=10) = (3, 2, 2)."""
    assert decode_phase0_cmd(0b11, 0b10, 0b10) == DRAMCommand.WR


def test_decode_phase0_rate2_each_cmd():
    """For DFI_RATE=2 each command should be detectable when packed in
    phase 0 with phase 1 held NOP. Pre-fix the BFM read the full 2-bit
    values and looked them up against single-bit decode keys — every
    real command silently decoded to NOP."""
    # Phase 1 NOP = (ras=1, cas=1, we=1) = bits 1,1,1 → MSB pattern
    nop_bits = (1, 1, 1)
    expected = [
        ((0, 1, 1), DRAMCommand.ACT),
        ((1, 0, 1), DRAMCommand.RD),
        ((1, 0, 0), DRAMCommand.WR),
        ((0, 1, 0), DRAMCommand.PRE),
        ((0, 0, 1), DRAMCommand.REF),
        ((0, 0, 0), DRAMCommand.MRS),
        ((1, 1, 1), DRAMCommand.NOP),
    ]
    for (r0, c0, w0), cmd in expected:
        packed_ras = (nop_bits[0] << 1) | r0
        packed_cas = (nop_bits[1] << 1) | c0
        packed_we  = (nop_bits[2] << 1) | w0
        got = decode_phase0_cmd(packed_ras, packed_cas, packed_we)
        assert got == cmd, (
            f"DFI_RATE=2 packed {{phase1=NOP, phase0=({r0},{c0},{w0})}}"
            f" should decode to {cmd}, got {got}. The BFM is ignoring "
            "the phase-0 mask — G-01a regression."
        )


def test_decode_phase0_rate4_each_cmd():
    """Same coverage at DFI_RATE=4 — three phases of NOP above phase 0."""
    expected = [
        ((0, 1, 1), DRAMCommand.ACT),
        ((1, 0, 1), DRAMCommand.RD),
        ((1, 0, 0), DRAMCommand.WR),
        ((0, 1, 0), DRAMCommand.PRE),
        ((0, 0, 1), DRAMCommand.REF),
        ((0, 0, 0), DRAMCommand.MRS),
    ]
    # Phases 1,2,3 = NOP → (ras=1, cas=1, we=1) on each
    upper_ras = 0b1110
    upper_cas = 0b1110
    upper_we  = 0b1110
    for (r0, c0, w0), cmd in expected:
        packed_ras = upper_ras | r0
        packed_cas = upper_cas | c0
        packed_we  = upper_we  | w0
        assert decode_phase0_cmd(packed_ras, packed_cas, packed_we) == cmd


# ---------------------------------------------------------------------
# slice_phase_wrdata — DFI_RATE=1 (sanity) + DFI_RATE>1 (regression)
# ---------------------------------------------------------------------


def test_slice_wrdata_rate1_single_phase():
    """DFI_RATE=1: 1-bit wrdata_en, 64-bit wrdata."""
    data = 0xDEADBEEF_CAFEBABE
    mask = 0x00
    out = slice_phase_wrdata(full_wrdata=data, full_mask=mask,
                             wrdata_en_bits=1, beat_bytes=8)
    assert out == [(0, data, 0x00)]


def test_slice_wrdata_rate2_phase0_only():
    """DFI_RATE=2 with phase-0 only valid — what the v1 controller does.
    Pre-fix this returned the full 128-bit value and overflowed
    beat_bytes when stored into the memory model."""
    phase0_data = 0xDEADBEEF_CAFEBABE
    phase1_data = 0x11111111_22222222
    packed = (phase1_data << 64) | phase0_data
    packed_mask = (0xAA << 8) | 0x55
    out = slice_phase_wrdata(full_wrdata=packed, full_mask=packed_mask,
                             wrdata_en_bits=0b01, beat_bytes=8)
    assert out == [(0, phase0_data, 0x55)]


def test_slice_wrdata_rate2_phase1_only():
    """DFI_RATE=2 with phase-1 only valid — exercises the shift path."""
    phase0_data = 0x11111111_22222222
    phase1_data = 0xDEADBEEF_CAFEBABE
    packed = (phase1_data << 64) | phase0_data
    packed_mask = (0xAA << 8) | 0x55
    out = slice_phase_wrdata(full_wrdata=packed, full_mask=packed_mask,
                             wrdata_en_bits=0b10, beat_bytes=8)
    assert out == [(1, phase1_data, 0xAA)]


def test_slice_wrdata_rate2_both_phases():
    """DFI_RATE=2 with both phases valid — emits both beats LSB→MSB."""
    phase0_data = 0x0000_0000_DEAD_BEEF
    phase1_data = 0xCAFE_BABE_FEED_C0DE
    packed = (phase1_data << 64) | phase0_data
    out = slice_phase_wrdata(full_wrdata=packed, full_mask=0,
                             wrdata_en_bits=0b11, beat_bytes=8)
    assert out == [(0, phase0_data, 0), (1, phase1_data, 0)]


def test_slice_wrdata_idle():
    """wrdata_en=0 → no phases."""
    assert slice_phase_wrdata(full_wrdata=0xDEADBEEF, full_mask=0xFF,
                              wrdata_en_bits=0, beat_bytes=8) == []
