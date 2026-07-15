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


# _FUTURE_HOOKS: as the next PHY needs a new timing dimension, add a field to
# DFITimingProfile with a safe default and honor it in DFISlavePHY. Kept as a
# note (not code) so the hook surface stays discoverable in one place.
