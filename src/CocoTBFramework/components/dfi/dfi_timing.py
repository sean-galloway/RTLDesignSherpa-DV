# SPDX-License-Identifier: MIT
"""PHY-agnostic DFI data-timing hooks for :class:`DFISlavePHY`.

The DFI *command* protocol is fixed, but every PHY has its own *data*-return
contract: when read data appears relative to the command, whether the
controller's ``dfi_rddata_en`` gates it, where write data is sampled, and so
on. Rather than hard-code any one PHY (a7ddrphy today, DDR3/DDR4/LPDDR next),
this module captures each such contract as an independent, defaulted HOOK on
:class:`DFITimingProfile`. Configure the hooks to model a specific PHY; leave
them at defaults for an idealized, self-timed loopback.

Design intent (per project direction): keep the model generic but expose ALL
the hooks needed to specialize it, and make it trivial to add MORE hooks when
the next PHY needs them — every field has a safe default, so adding one never
breaks an existing profile or caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Read-return anchor: what the rddata_valid schedule is measured from.
READ_REF_COMMAND = "command"      # fixed latency after the READ COMMAND (DRAM-like)
READ_REF_RDDATA_EN = "rddata_en"  # latency after the controller asserts dfi_rddata_en

# Write-capture point: where the model samples dfi_wrdata.
WRITE_REF_WRDATA_EN = "wrdata_en"  # capture whenever dfi_wrdata_en fires (DFI handshake)
WRITE_REF_COMMAND = "command"      # sample the wire at command+write_latency (DQ window)


@dataclass
class DFITimingProfile:
    """One PHY's DFI data-timing contract, as independent hooks.

    Read hooks
    ----------
    read_ref        : READ_REF_COMMAND | READ_REF_RDDATA_EN — the anchor event
                      for the rddata_valid schedule.
    read_latency    : cycles from the anchor to rddata_valid. None => JEDEC CL
                      (only meaningful for READ_REF_COMMAND; for RDDATA_EN it is
                      the enable->valid delay and defaults to 0 when None).
    read_en_gated   : if True, rddata_valid is driven ONLY on cycles the
                      controller asserts dfi_rddata_en (a capture-window gate).
                      If False, the model self-times and ignores rddata_en.

    Write hooks
    -----------
    write_ref       : WRITE_REF_WRDATA_EN | WRITE_REF_COMMAND — where wrdata is
                      sampled.
    write_latency   : cycles from the WR command to the sample point (only for
                      WRITE_REF_COMMAND). None => JEDEC CWL.

    Add new PHY hooks below with a SAFE default (see _FUTURE_HOOKS) — e.g.
    read/write preamble & postamble, per-phase DQ skew, DBI, read/write CRC
    cycles, gear-down, split tphy_rdlat/tphy_wrlat, DQS gate window, etc.
    """
    name: str = "ideal"

    # ---- read data return ----
    read_ref: str = READ_REF_COMMAND
    read_latency: Optional[int] = None
    read_en_gated: bool = False
    # Free-running ISERDES model (a7ddrphy-faithful). When True, the read DATA
    # pipeline is anchored to the READ COMMAND at read_latency and advances
    # INDEPENDENTLY of dfi_rddata_en (like a real ISERDES continuously shifting
    # out captured DQ). rddata_valid is the controller's rddata_en delayed by
    # `read_valid_latency` sys-cycles. The DQ bus HOLDS its last presented word
    # until the command pipeline overwrites it. If the controller fires
    # rddata_en at a cadence that slips relative to the command-anchored data,
    # the valid strobe samples a STALE (previous read's) or ZERO word -> the
    # one-read shift the on-silicon ILA showed. read_en_gated resynchronizes
    # data to enable and thus HIDES this; free-running does not.
    read_free_running: bool = False
    read_valid_latency: Optional[int] = None  # rddata_en -> rddata_valid delay

    # ---- BL < 2*nphases anchored-phase read (a7ddrphy fixed 8-slot deint) ----
    # The Artix-7 a7ddrphy is a FIXED BL8 / 8-slot de-interleaver: a full BL8
    # read fills all `nphases` DFI phases. A SHORTER burst (BL4 at nphases=4)
    # returns only BL/2 DDR beats, filling only BL/(2*words_per_beat) of the
    # phases — ANCHORED at the controller's rd_phase. The phases the burst does
    # NOT drive hold the PREVIOUS read's beats (stale), NOT the ideal all-phase
    # data. Set read_bl_anchored=True to model this: a burst delivering fewer
    # device-words than one full DFI cycle is placed in its rd_phase-anchored
    # phase slots and the remaining phase slots retain the prior read's words.
    # read_phase_pairs = device-word phase-pairs (K device-words) an anchored
    # burst occupies is derived from the burst size at runtime, so no extra
    # knob is needed. Default False => bit-identical all-phase behavior.
    read_bl_anchored: bool = False

    # ---- write data capture ----
    write_ref: str = WRITE_REF_WRDATA_EN
    write_latency: Optional[int] = None

    def __post_init__(self) -> None:
        if self.read_ref not in (READ_REF_COMMAND, READ_REF_RDDATA_EN):
            raise ValueError(f"bad read_ref {self.read_ref!r}")
        if self.write_ref not in (WRITE_REF_WRDATA_EN, WRITE_REF_COMMAND):
            raise ValueError(f"bad write_ref {self.write_ref!r}")

    # ------------------------------------------------------------------ presets
    @staticmethod
    def ideal() -> "DFITimingProfile":
        """Idealized loopback: read self-timed off the command at JEDEC CL,
        ungated; write captured on wrdata_en. Matches the legacy BFM default —
        maximally permissive, good for functional (not timing) checks."""
        return DFITimingProfile(name="ideal")

    @staticmethod
    def a7ddrphy(read_latency: int, write_latency: int = 0,
                 read_en_gated: bool = False) -> "DFITimingProfile":
        """Xilinx Artix-7 a7ddrphy (DDR2/DDR3). The PHY drives dfi_rddata +
        dfi_rddata_valid a fixed latency after the READ COMMAND; the
        controller's dfi_rddata_en is its OWN capture-window concern, so the
        model does NOT gate on it by default (read_en_gated=False) — a
        controller that mis-times rddata_en still mis-captures the correctly
        presented data. `read_latency` = command->rddata_valid in sys cycles
        (calibrate from the board's t_rddata_en / rddata_delay so the presented
        cycle matches the aligner's expectation). Write data is sampled on
        dfi_wrdata_en; `write_latency` from t_phy_wrlat (0 for pre-pull). Set
        read_en_gated=True only for a PHY that truly withholds rddata_valid
        until rddata_en (needs the return latency aligned to the enable window,
        else it stalls — see the profile hook docs)."""
        return DFITimingProfile(
            name="a7ddrphy",
            read_ref=READ_REF_COMMAND,
            read_latency=int(read_latency),
            read_en_gated=bool(read_en_gated),
            write_ref=WRITE_REF_WRDATA_EN,
            write_latency=int(write_latency),
        )

    @staticmethod
    def a7ddrphy_free_running(read_latency: int, read_valid_latency: int,
                              write_latency: int = 0) -> "DFITimingProfile":
        """Faithful a7ddrphy read pipeline. The DQ/ISERDES DATA free-runs off
        the READ COMMAND at `read_latency` sys-cycles (holding its last word on
        the bus), while dfi_rddata_valid is the controller's dfi_rddata_en
        delayed by `read_valid_latency`. Data and valid are DECOUPLED, so a
        controller whose rddata_en cadence slips vs the command-anchored data
        samples a stale/zero word -> reproduces the on-silicon consecutive-read
        one-slot shift. `write_latency` from t_phy_wrlat."""
        return DFITimingProfile(
            name="a7ddrphy_free_running",
            read_ref=READ_REF_COMMAND,
            read_latency=int(read_latency),
            read_en_gated=False,
            read_free_running=True,
            read_valid_latency=int(read_valid_latency),
            write_ref=WRITE_REF_WRDATA_EN,
            write_latency=int(write_latency),
        )

    @staticmethod
    def a7ddrphy_bl4(read_latency: int, write_latency: int = 0,
                     read_en_gated: bool = False) -> "DFITimingProfile":
        """Faithful a7ddrphy for a BL < 2*nphases read (BL4 on the fixed
        nphases=4 Artix-7 PHY). The PHY de-interleaves a full BL8 read across
        all 4 DFI phases; a BL4 read fills only the 2 rd_phase-anchored phases
        and the OTHER 2 phases hold the PREVIOUS read's beats (stale). The
        controller (pumice) captures all 4 phases as one 128b DFI word, so it
        gets the anchored pair correct and the other pair STALE -> exactly the
        on-silicon p0,p1-correct / p2,p3-stale (beats_mismatched == 2*txn)
        fingerprint. read_ref=command + read_bl_anchored=True. Write path
        (write_latency, wrdata_en) is unaffected — writes drive all phases
        cleanly, matching the board."""
        return DFITimingProfile(
            name="a7ddrphy_bl4",
            read_ref=READ_REF_COMMAND,
            read_latency=int(read_latency),
            read_en_gated=bool(read_en_gated),
            read_bl_anchored=True,
            write_ref=WRITE_REF_WRDATA_EN,
            write_latency=int(write_latency),
        )

    @staticmethod
    def strict_dram(read_latency: int, write_latency: int) -> "DFITimingProfile":
        """Idealized real-DRAM DQ window: read returns a fixed latency after
        the command (ungated), write is SAMPLED at command+write_latency off
        the wire (ignores wrdata_en) so late/mis-cadenced wrdata reads back
        wrong. Useful to stress the controller's fixed-offset data alignment."""
        return DFITimingProfile(
            name="strict_dram",
            read_ref=READ_REF_COMMAND, read_latency=int(read_latency),
            read_en_gated=False,
            write_ref=WRITE_REF_COMMAND, write_latency=int(write_latency),
        )


# =============================================================================
# a7ddrphy BL < 2*nphases anchored-phase READ CONTRACT
# =============================================================================
# This is the SINGLE, AUTHORITATIVE statement of the a7ddrphy short-burst read
# behavior. The DV BFM (DFISlavePHY) honors it; the pumice RTL read aligner
# (pumice_dfi_rd_aligner.sv) MUST later assert the IDENTICAL rule. Keep this
# function the one place the mask is derived so both sides reference the same
# arithmetic — do NOT reimplement the mask inline anywhere else.
#
# THE RULE (proven on silicon, task #143/#146; supersedes the earlier gear-ratio
# theory, which was WRONG — the board built at DFI_RATE==nphases==4 STILL read
# exactly 2 of every 4 device-words wrong):
#
#   The Artix-7 a7ddrphy is a FIXED nphases-slot (8-slot for nphases=4) BL8
#   de-interleaver. One DFI cycle exposes
#       words_per_cycle = nphases * words_per_beat        (device-word slots)
#   A FULL BL8 read (bl == 2*nphases DDR beats) fills ALL words_per_cycle slots.
#   A SHORT burst delivers
#       burst_slots = bl        (one device word per DDR beat on a narrow device)
#   -- see bl_anchored_slot_mask below -- and fills ONLY the
#   rd_phase-ANCHORED contiguous slot run. The slots the short burst does NOT
#   drive hold the PREVIOUS read's beats (STALE), NOT this burst's data and NOT
#   zeros. A controller that captures ALL words_per_cycle slots as one wide DFI
#   word (as pumice's aligner does today) therefore gets the anchored run correct
#   and the remaining run STALE -> beats_mismatched == (non-anchored slots) per
#   read. For BL4 on nphases=4 x16 that is exactly 4 anchored + 4 stale ... but
#   the controller only gathers the low DFI word (K device-words per phase, the
#   phases it believes the burst occupies), so the on-silicon fingerprint is
#   2 correct / 2 stale device-words per captured BL4 read == 2*txn.


def bl_anchored_slot_mask(bl: int, nphases: int, words_per_beat: int,
                          rd_phase: int) -> "tuple[int, int, int]":
    """Derive the rd_phase-anchored device-word slot layout for a short burst.

    THIS IS THE CONTRACT the pumice RTL read aligner must mirror verbatim.

    Args
    ----
    bl              : JEDEC burst length in DDR beats (BL4 => 4, BL8 => 8).
    nphases         : PHY phase count / DFI gear (a7ddrphy is FIXED 4).
    words_per_beat  : device words packed into one DFI phase's data slice
                      (K; x16 device on a 32b phase => 2). MUST be a power of 2.
    rd_phase        : the DFI phase the controller anchors this read to (its
                      rdphase; a7ddrphy derives it from CL). 0 <= rd_phase < nphases.

    Returns
    -------
    (words_per_cycle, first_slot, burst_slots)
      words_per_cycle : total device-word slots one DFI cycle exposes
                        (== nphases * words_per_beat).
      first_slot      : index of the first device-word slot this burst drives
                        (the anchor = rd_phase * words_per_beat).
      burst_slots     : number of contiguous device-word slots this burst drives.

    The anchored slot set is therefore
        { first_slot, first_slot+1, ..., first_slot+burst_slots-1 }  (mod wrap),
    and EVERY OTHER slot in [0, words_per_cycle) holds the previous read's data.

    Requirements (asserted — the RTL assertion mirrors these):
      * nphases, words_per_beat are powers of two.
      * bl is even (DDR beats come in pairs) and bl <= 2*nphases (short/equal).
      * A full burst (bl == 2*nphases) drives ALL slots (burst_slots ==
        words_per_cycle, no stale slots) — the mask degenerates to identity.
    """
    assert nphases >= 1 and (nphases & (nphases - 1)) == 0, \
        f"nphases must be a power of two, got {nphases}"
    assert words_per_beat >= 1 and (words_per_beat & (words_per_beat - 1)) == 0, \
        f"words_per_beat must be a power of two, got {words_per_beat}"
    assert bl >= 2 and (bl % 2) == 0, f"bl must be an even DDR beat count, got {bl}"
    assert bl <= 2 * nphases, \
        f"bl={bl} exceeds a full DFI cycle (2*nphases={2*nphases})"
    assert 0 <= rd_phase < nphases, \
        f"rd_phase={rd_phase} out of range [0,{nphases})"

    words_per_cycle = nphases * words_per_beat
    # A BL of `bl` DDR beats delivers `bl` device words per x16 command? No: a BL
    # read delivers `bl` DDR beats; each DDR beat is one device word for a narrow
    # (x16) device, so the burst delivers `bl` device words. Those occupy
    # bl // words_per_beat DFI phases, i.e. `bl` contiguous device-word slots
    # anchored at rd_phase. (bl == 2*nphases => bl == words_per_cycle => all slots.)
    burst_slots = bl
    assert burst_slots <= words_per_cycle, \
        f"burst_slots={burst_slots} exceeds words_per_cycle={words_per_cycle}"
    first_slot = rd_phase * words_per_beat
    assert 0 <= first_slot < words_per_cycle, \
        f"anchor first_slot={first_slot} out of range [0,{words_per_cycle})"
    return words_per_cycle, first_slot, burst_slots


# _FUTURE_HOOKS: as the next PHY needs a new timing dimension, add a field to
# DFITimingProfile with a safe default and honor it in DFISlavePHY. Kept as a
# note (not code) so the hook surface stays discoverable in one place.
