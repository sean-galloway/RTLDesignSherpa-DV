# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Event dataclasses returned by per-version behavior methods.

One type per semantic-shift area. Callers pattern-match on type
rather than branching on enum kinds — cleaner with Python ``match``
statements and gives each event independent fields.

These types are **value objects** — immutable, hashable, comparable.
The behavior classes construct them at the boundary; downstream
consumers can route them to scoreboards / loggers / assertions.

Wire-level notes are spec-verified (v2.1.1 / v3.1 / v4.0 / v5.2 /
v6.0 signal tables — see dfi_signal_catalog).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------
# CRC / alert (v3.0+: dfi_alert_n, active low; v6.0: dfi_alert)
# ---------------------------------------------------------------------


class CRCKind(str, Enum):
    DRAM_CRC = "dram_crc"     # Write CRC verified at the DRAM (DDR4/DDR5)
    LINK_CRC = "link_crc"     # Link DQ CRC (v5.2+, DDR5 MRDIMM Mux Mode)
    CA_PARITY = "ca_parity"   # CA parity — indistinguishable from CRC
    #                           on dfi_alert_n at the DFI boundary


@dataclass(frozen=True)
class CRCEvent:
    """dfi_alert_n went active. DDR4+ report both write-CRC and
    CA-parity errors on the same wire, so ``kind`` is DRAM_CRC unless
    the caller has out-of-band knowledge to refine it."""
    kind: CRCKind
    slice_idx: int = 0
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Update (bidirectional since v2.1; self-refresh-exit tie-in v4.0)
# ---------------------------------------------------------------------


class UpdateState(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    SELF_REFRESH_EXIT = "self_refresh_exit"   # v4.0+ pre-SRX handshake


@dataclass(frozen=True)
class UpdateEvent:
    state: UpdateState
    initiator: str            # "mc" (ctrlupd) or "phy" (phyupd)
    update_type: int = 0      # dfi_phyupd_type (PHY-initiated only)
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# PHY Master (v4.0) / PHY Managed (v5.2 rename)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TakeoverEvent:
    """PHY requested ownership of the DFI/DRAM buses.

    ``takeover_type`` is dfi_phymstr_type / dfi_phymngd_type (selects
    the tphymstr_type0-3 duration class); ``state_sel`` and
    ``cs_state`` mirror the request's DRAM-state qualifier wires.
    """
    reason: str               # "phy_master" (v4.x) / "phy_managed" (v5.2+)
    takeover_type: int = 0
    state_sel: int = 0
    cs_state: int = 0
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Disconnect protocol (v4.0-v5.x; removed in v6.0). A disconnect is
# the act of breaking an in-flight ctrlupd/phyupd/phymstr handshake;
# dfi_disconnect_error qualifies it as QOS (0) or error (1).
# ---------------------------------------------------------------------


class DisconnectPhase(str, Enum):
    REQUEST = "request"
    ACK = "ack"
    RELEASE = "release"


@dataclass(frozen=True)
class DisconnectEvent:
    phase: DisconnectPhase
    error: bool = False       # dfi_disconnect_error: False=QOS, True=error
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Frequency change — dfi_init_start / dfi_init_complete handshake in
# EVERY version (there is no request wire of its own). v4.0 added the
# dfi_frequency indicator; v5.2 split ratios and added FSP.
# ---------------------------------------------------------------------


class FreqChangeProtocol(str, Enum):
    BASIC = "basic"           # v2.1-v3.x: init_start toggle, no indicator
    ACKNOWLEDGED = "ack"      # PHY de-asserted init_complete in window
    NOT_ACKNOWLEDGED = "nak"  # PHY ignored the request (offer withdrawn)


@dataclass(frozen=True)
class FreqChangeEvent:
    protocol: FreqChangeProtocol
    frequency_code: Optional[int] = None   # dfi_frequency (v4.0+)
    freq_ratio: Optional[int] = None       # dfi_freq_ratio (v2.1-v4.0)
    cmd_freq_ratio: Optional[int] = None   # dfi_cmd_freq_ratio (v5.2+)
    data_freq_ratio: Optional[int] = None  # dfi_data_freq_ratio (v5.2+)
    freq_fsp: Optional[int] = None         # dfi_freq_fsp (v5.2+)
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Training (v2.1-v4.0; interface removed in v5.x)
# ---------------------------------------------------------------------


class TrainingPhase(str, Enum):
    READ_LEVELING = "read_lvl"    # dfi_rdlvl_* (v2.1+)
    GATE_TRAINING = "gate"        # dfi_rdlvl_gate_* (v2.1+)
    WRITE_LEVELING = "write_lvl"  # dfi_wrlvl_* (v2.1+, DDR3/DDR4)
    CA_TRAINING = "ca"            # dfi_calvl_* (v3.1+, LPDDR3/LPDDR4)
    DQ_TRAINING = "dq"            # dfi_wdqlvl_* (v4.0)
    DB_TRAINING = "db"            # dfi_db_train_* (v4.0, DDR4 LRDIMM)
    PHY_REQUESTED = "phy_req"     # dfi_phylvl_req_cs_n (v3.1)


@dataclass(frozen=True)
class TrainingEvent:
    phase: TrainingPhase
    slice_idx: int = 0        # v4.0+ per-slice; 0 for older
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Error interface (v3.0+; dfi_phy_error/_info rename in v6.0)
# ---------------------------------------------------------------------


class ErrorKind(str, Enum):
    PARITY = "parity"
    CRC = "crc"
    TRAINING_FAIL = "training_fail"
    OTHER = "other"


@dataclass(frozen=True)
class ErrorEvent:
    kind: ErrorKind
    code: int = 0             # dfi_error_info / dfi_phy_error_info
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# CA parity (v2.1.1 DDR3 DIMM parity via dfi_parity_error; folded
# into dfi_alert_n from v3.0)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class CAParityEvent:
    """Command-parity error reported by the PHY.

    v2.1: dedicated dfi_parity_error wire (DDR3 registered DIMMs).
    v3.0+: parity errors share dfi_alert_n with write-CRC errors and
    surface as :class:`CRCEvent` instead — see the behavior classes.
    """
    parity_bit_expected: int = 0
    parity_bit_received: int = 0
    timestamp_ns: float = 0.0


# ---------------------------------------------------------------------
# Low power control (v2.1: lp_req/lp_ack; v3.1: ctrl/data req split;
# v5.1: ctrl/data ack + wakeup split)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class LowPowerEvent:
    """MC offered a low-power opportunity window.

    ``channel`` is "shared" (v2.1 dfi_lp_req), "ctrl" or "data"
    (v3.1+ split requests). ``wakeup`` carries the wakeup-time
    encoding valid with the request.
    """
    channel: str              # "shared" | "ctrl" | "data"
    wakeup: int = 0
    timestamp_ns: float = 0.0
