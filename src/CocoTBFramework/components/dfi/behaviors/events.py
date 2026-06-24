# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Event dataclasses returned by per-version behavior methods.

One type per semantic-shift area, per the catalog. Callers pattern-
match on type rather than branching on enum kinds — cleaner with
Python ``match`` statements and gives each event independent fields.

These types are **value objects** — immutable, hashable, comparable.
The behavior classes construct them at the boundary; downstream
consumers can route them to scoreboards / loggers / assertions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------
# CRC (introduced v3.0)
# ---------------------------------------------------------------------


class CRCKind(str, Enum):
    DRAM_CRC = "dram_crc"     # Write CRC verified at the DRAM
    LINK_CRC = "link_crc"     # Link DQ CRC (v5+)
    CA_PARITY = "ca_parity"   # CA parity (DDR4+); appears as CRC event class for uniformity


@dataclass(frozen=True)
class CRCEvent:
    kind: CRCKind
    slice_idx: int = 0        # which data slice raised the error
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Update (existed v2.1; rewritten v3.0; self-refresh exit v4.0)
# ---------------------------------------------------------------------


class UpdateState(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    SELF_REFRESH_EXIT = "self_refresh_exit"   # v4.0+


@dataclass(frozen=True)
class UpdateEvent:
    state: UpdateState
    initiator: str            # "mc" or "phy"
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# PHY Master / PHY Managed (introduced v4.0)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TakeoverEvent:
    """PHY has taken ownership of the DFI bus.

    ``reason`` is a freeform tag from the spec (e.g., 'recalibration',
    'autonomous_refresh', 'training'); the BFM doesn't enforce a fixed
    enum because the spec text varies.
    """
    reason: str
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Disconnect protocol (introduced v4.0)
# ---------------------------------------------------------------------


class DisconnectPhase(str, Enum):
    REQUEST = "request"
    ACK = "ack"
    RELEASE = "release"


@dataclass(frozen=True)
class DisconnectEvent:
    phase: DisconnectPhase
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Frequency change (v2.1 basic; v4.0 added Ack/Not-Ack split)
# ---------------------------------------------------------------------


class FreqChangeProtocol(str, Enum):
    BASIC = "basic"           # v2.1-v3.x
    ACKNOWLEDGED = "ack"      # v4.0+
    NOT_ACKNOWLEDGED = "nak"  # v4.0+


@dataclass(frozen=True)
class FreqChangeEvent:
    protocol: FreqChangeProtocol
    old_freq_mhz: Optional[float] = None
    new_freq_mhz: Optional[float] = None
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Training (introduced v3.0; expanded v3.1 / v4.0)
# ---------------------------------------------------------------------


class TrainingPhase(str, Enum):
    READ_LEVELING = "read_lvl"
    WRITE_LEVELING = "write_lvl"
    DQ_TRAINING = "dq"
    CA_TRAINING = "ca"
    DB_TRAINING = "db"        # v4.0+ (LPDDR4 DB)
    PHY_REQUESTED = "phy_req" # v3.1+ — initiated by PHY, not MC


@dataclass(frozen=True)
class TrainingEvent:
    phase: TrainingPhase
    slice_idx: int = 0        # v4.0+ per-slice; ignored for older
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Error interface (introduced v3.0)
# ---------------------------------------------------------------------


class ErrorKind(str, Enum):
    PARITY = "parity"
    CRC = "crc"
    TRAINING_FAIL = "training_fail"
    OTHER = "other"


@dataclass(frozen=True)
class ErrorEvent:
    kind: ErrorKind
    code: int = 0
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# CA parity (introduced v3.0 for DDR4+)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class CAParityEvent:
    """CA bus parity error reported by the PHY.

    Kept separate from CRCEvent even though they're conceptually
    related: parity is per-command on the address path; CRC is on
    the data path. Different scoreboard plumbing downstream.
    """
    parity_bit_expected: int = 0
    parity_bit_received: int = 0
    timestamp_ns: float = 0.0
