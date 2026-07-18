# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
"""Unit tests for DFISlavePHY's faithful a7ddrphy BL4 phase-anchored
de-interleaver (task #146).

The Artix-7 a7ddrphy exposes ONE fixed words_per_cycle-slot DFI word per DFI
cycle (8 slots for nphases=4 x16: 4 phases x 2 device words). This test pins the
TWO faithful primitives the BFM (DFISlavePHY) is built from:

  1. decode_all_phases  — decode a command at EVERY selected DFI phase, so the
     BFM models the multi-command-per-cycle packing the fix issues (two BL4 RDs
     at phases {P, P+2} in ONE cycle). The legacy single-command path decoded
     phase 0 only and would have dropped the second command.

  2. deinterleave_read_window — build one 8-slot window from the reads issued in
     a cycle. This ONE model reproduces BOTH:
       * BUG (1 RD/cycle): the read fills only its rd_phase-anchored 4 slots; the
         other 4 HOLD the previous read's device words (STALE) -> 4 real, 4 stale.
       * FIX (2 RDs/cycle at {0,2}): both anchored runs written -> 8 real, 0 stale.

The anchored slot layout comes from the SAME shared contract the RTL assertion
mirrors (dfi_timing.bl_anchored_slot_mask), so this is not a hand-rolled model.

CRITICAL: PHASE-DISTINCT device words (never aliased), so a stale/misplaced slot
can never accidentally equal the expected slot and hide the corruption.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.dfi_slave_phy import (
    decode_all_phases,
    deinterleave_read_window,
)

# ---- board rate4_x16 geometry (the fixed a7ddrphy 8-slot de-interleave) ----
NPHASES = 4          # a7ddrphy fixed phase count (== board DFI_RATE)
K = 2                # words_per_beat: x16 device (2B) in a 32b DFI phase
WPC = NPHASES * K    # 8 device-word slots per DFI cycle
BL = 4               # DDR2 BL4 -> 4 device words per RD command


def _distinct(base):
    """4 phase-distinct device words for one BL4 read (never aliased)."""
    return [base + i for i in (0x1000, 0x2000, 0x3000, 0x4000)]


# ---------------------------------------------------------------------
# decode_all_phases — multi-command-per-cycle decode
# ---------------------------------------------------------------------

def test_decode_all_phases_rate1_single():
    """DFI_RATE=1: one command on phase 0 (legacy-equivalent)."""
    # phase 0 = RD (ras=1,cas=0,we=1), cs_n=0 selected
    got = decode_all_phases(cs_n_bus=0b0, ras_n_bus=0b1, cas_n_bus=0b0,
                            we_n_bus=0b1, dfi_rate=1)
    assert got == [(0, DRAMCommand.RD)]


def test_decode_all_phases_rate4_phase0_only():
    """Only phase 0 selected -> single decode; upper phases NOP/deselected.
    This is the on-board BUG cadence (ONE RD per DFI cycle)."""
    # phase 0 RD selected (cs_n bit0=0); phases 1..3 deselected (cs_n=1) + NOP.
    cs = 0b1110
    ras = 0b1111   # phase0 ras=1 (RD)
    cas = 0b1110   # phase0 cas=0 (RD)
    we = 0b1111    # phase0 we=1 (RD)
    got = decode_all_phases(cs, ras, cas, we, dfi_rate=4)
    assert got == [(0, DRAMCommand.RD)]


def test_decode_all_phases_rate4_two_reads_phase0_and_2():
    """The FIX cadence: TWO RD commands issued in ONE DFI cycle at phases {0,2}.
    The legacy phase-0-only decoder would have seen only the first — this one
    returns BOTH, each with its own phase (its anchor)."""
    # RD per-phase bits: ras=1, cas=0, we=1. NOP: ras=cas=we=1.
    # phases 0 and 2 = RD selected (cs_n=0), phases 1,3 = deselected NOP.
    cs = 0b1010   # bit0=0, bit2=0 selected; bit1=1, bit3=1 deselected
    ras = 0b1111  # RD has ras=1 on all; NOP also ras=1
    cas = 0b1010  # cas=0 on phases 0,2 (RD); cas=1 on 1,3 (NOP)
    we = 0b1111   # we=1 on RD and NOP alike
    got = decode_all_phases(cs, ras, cas, we, dfi_rate=4)
    assert got == [(0, DRAMCommand.RD), (2, DRAMCommand.RD)]


def test_decode_all_phases_skips_deselected():
    """A phase with a valid-looking control encoding but cs_n HIGH is NOT a
    command (the PHY only accepts a phase whose cs_n is asserted)."""
    # phase 0 looks like RD on the control bus, but cs_n bit0 = 1 (deselected).
    got = decode_all_phases(cs_n_bus=0b1111, ras_n_bus=0b1,
                            cas_n_bus=0b0, we_n_bus=0b1, dfi_rate=4)
    assert got == []


# ---------------------------------------------------------------------
# deinterleave_read_window — BUG (1 RD/cycle) vs FIX (2 RDs/cycle)
# ---------------------------------------------------------------------

def test_deinterleave_one_read_leaves_stale():
    """BUG: one BL4 RD/cycle fills only its rd_phase-anchored 4 slots; the other
    4 slots HOLD the previous window (STALE previous read's REAL data). This is
    the on-silicon 4 real + 4 stale -> beats_mismatched == 2*txn mechanism."""
    A = _distinct(0x0100)      # read A, anchored at phase 2 -> slots[4:8]
    B = _distinct(0x0200)      # read B, anchored at phase 0 -> slots[0:4]

    # Cycle 1: only read A at phase 2 -> occupies the HIGH phase-pair slots[4:8].
    w1 = deinterleave_read_window(prev_window=[], bursts=[(2, A)],
                                  words_per_cycle=WPC, nphases=NPHASES,
                                  words_per_beat=K)
    assert w1[4:8] == A                    # anchored run = real
    assert w1[0:4] == [0, 0, 0, 0]         # untouched slots = stale (zero here)

    # Cycle 2: only read B at phase 0 -> slots[0:4]. Slots[4:8] now HOLD read A's
    # OLD data (stale-previous) — a genuine value, NOT zero, NOT read B's data.
    w2 = deinterleave_read_window(prev_window=w1, bursts=[(0, B)],
                                  words_per_cycle=WPC, nphases=NPHASES,
                                  words_per_beat=K)
    assert w2[0:4] == B                     # read B anchored run = real
    assert w2[4:8] == A                     # STALE: holds read A (a real value)
    # A grab-all aligner captures all 8 slots as read B's word: 4 correct + 4
    # stale (read A) -> per-BL4 2/4 wrong == the board beats_mismatched == 2*txn.
    assert w2[4:8] != B[0:4]                # the stale half is NOT read B


def test_deinterleave_two_reads_phase0_and_2_fully_packed():
    """FIX: TWO BL4 RDs in ONE cycle at phases {0, 2} -> anchored runs
    {slots[0:4], slots[4:8]} both written -> 8 real device words, ZERO stale."""
    A = _distinct(0x0100)      # anchored at phase 0 -> slots[0:4]
    B = _distinct(0x0200)      # anchored at phase 2 -> slots[4:8] (2*K=4)
    # Seed a non-zero previous window so any leftover stale would be VISIBLE.
    prev = list(range(0xF0, 0xF8))
    w = deinterleave_read_window(prev_window=prev,
                                 bursts=[(0, A), (2, B)],
                                 words_per_cycle=WPC, nphases=NPHASES,
                                 words_per_beat=K)
    assert w[0:4] == A
    assert w[4:8] == B
    # No slot retained the stale seed -> zero stale, fully packed.
    assert w == A + B
    assert not any(w[i] == prev[i] and prev[i] not in (A + B) for i in range(8))


def test_deinterleave_phase2_anchor_first_slot():
    """The phase-2 anchor lands at first_slot = rd_phase*K = 4 (contract),
    so read B occupies the HIGH phase-pair — the packing the fix relies on."""
    from CocoTBFramework.components.dfi.dfi_timing import bl_anchored_slot_mask
    wpc, first, nslots = bl_anchored_slot_mask(bl=BL, nphases=NPHASES,
                                               words_per_beat=K, rd_phase=2)
    assert (wpc, first, nslots) == (8, 4, 4)


def test_deinterleave_full_burst_identity():
    """A full-window read (bl == words_per_cycle) drives ALL slots -> no stale,
    the degenerate case that never showed the board bug (BL8 x64)."""
    full = list(range(0x10, 0x18))       # 8 device words
    w = deinterleave_read_window(prev_window=[0xFF] * 8, bursts=[(0, full)],
                                 words_per_cycle=WPC, nphases=NPHASES,
                                 words_per_beat=K)
    assert w == full


def test_deinterleave_pattern_is_phase_distinct():
    """Guard the guard: the test pattern must be phase-distinct (a5a0 trap)."""
    assert len(set(_distinct(0x0100))) == BL
