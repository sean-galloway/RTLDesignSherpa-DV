# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Core types for the DFI signal envelope: version / memory / sub-
interface enums, width-key sentinels, and :class:`SignalSpec`.

Split out of ``dfi_signals`` so the catalog data
(``dfi_signal_catalog``) and the envelope API (``dfi_signals``) can
both import them without a cycle. Everything here is re-exported by
``dfi_signals`` — import from there in user code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional


class DFIVersion(str, Enum):
    """Supported DFI specification revisions.

    One representative per major line: V3_1 stands in for v3.0+v3.1,
    V5_2 for v5.0/5.1/5.2 (the 5.1 signal additions and 5.2 renames
    are encoded at V5_2 since the enum has no finer resolution).
    """

    V2_1 = "2.1"
    V3_1 = "3.1"
    V4_0 = "4.0"
    V5_2 = "5.2"
    V6_0 = "6.0"


class MemoryType(str, Enum):
    """DRAM technologies targetable across DFI v2.1-v6.0.

    Support varies by version — see SUPPORTED_MEMORY_BY_VERSION in
    ``dfi_signals``. v6.0 dropped DDR1-4 and LPDDR1-4 and added
    LPDDR6 + HBM4 (v6.0 revision history, 8 May 2026).
    """

    DDR1 = "ddr1"
    DDR2 = "ddr2"
    DDR3 = "ddr3"
    DDR4 = "ddr4"
    DDR5 = "ddr5"
    LPDDR1 = "lpddr1"
    LPDDR2 = "lpddr2"
    LPDDR3 = "lpddr3"
    LPDDR4 = "lpddr4"
    LPDDR5 = "lpddr5"
    LPDDR6 = "lpddr6"
    HBM4 = "hbm4"


class SubInterface(str, Enum):
    """DFI sub-interfaces that own signals, across v2.1-v6.0.

    Naming follows the latest spec ("Command Interface" — pre-v5.x
    books call it "Control Interface"). Feature sections that own no
    signals of their own (DBI, ECC, Link DQ CRC, multi-channel) are
    not sub-interfaces here; their signals live in the write/read
    data interfaces exactly as in the spec tables.
    """

    COMMAND = "command"          # "Control Interface" pre-v5.x
    WRITE_DATA = "write_data"
    READ_DATA = "read_data"
    UPDATE = "update"
    STATUS = "status"
    TRAINING = "training"        # v2.1-v4.0 only; removed in v5.x
    DB_TRAINING = "db_training"  # v4.0 only (DDR4 LRDIMM)
    LOW_POWER = "low_power"
    ERROR = "error"              # v3.0+
    PHY_MANAGED = "phy_managed"  # v4.0 "PHY Master"; renamed v5.2
    DISCONNECT = "disconnect"    # v4.0-v5.x; removed in v6.0
    MC_TO_PHY_MSG = "mc_to_phy_msg"  # v5.1+
    WCK_CONTROL = "wck_control"      # v5.1+ (LPDDR5/LPDDR6)


class SignalDirection(str, Enum):
    """Direction of a DFI signal from the MC's point of view."""

    MC_TO_PHY = "mc_to_phy"
    PHY_TO_MC = "phy_to_mc"


# ----------------------------------------------------------------------
# Width-key sentinels, resolved at BFM construction time from the
# user's width parameters. Names track the spec's width vocabulary
# ("DFI Data Width", "DFI Chip Select Width", ...).
# ----------------------------------------------------------------------

WIDTH_ADDR = "addr_width"
WIDTH_BANK = "bank_width"
WIDTH_BANK_GROUP = "bank_group_width"
WIDTH_CHIP_ID = "chip_id_width"
WIDTH_CS = "cs_width"
WIDTH_CTRL = "ctrl_width"
WIDTH_DATA = "data_width"
WIDTH_DATA_EN = "data_enable_width"
WIDTH_RD_VALID = "rd_valid_width"
WIDTH_DATA_DIV8 = "data_width_div_8"     # masks / dnv / dbi / crc / ecc
WIDTH_ALERT = "alert_width"
WIDTH_RANK = "rank_width"                # "DFI Physical Rank Width"
WIDTH_PER_SLICE = "per_slice"            # per-data-slice fanout signals
WIDTH_CS_X_DATA_EN = "cs_x_data_enable"  # v3.x rd/wrdata_cs_n
WIDTH_WCK = "wck_width"                  # WCK x slice-count products
WIDTH_ONE_BIT = "one_bit"
WIDTH_TWO_BITS = "two_bits"
WIDTH_THREE_BITS = "three_bits"
WIDTH_FIVE_BITS = "five_bits"
WIDTH_SIX_BITS = "six_bits"
WIDTH_EIGHT_BITS = "eight_bits"
WIDTH_SIXTEEN_BITS = "sixteen_bits"


_VERSION_RANK = {
    DFIVersion.V2_1: 21,
    DFIVersion.V3_1: 31,
    DFIVersion.V4_0: 40,
    DFIVersion.V5_2: 52,
    DFIVersion.V6_0: 60,
}


def version_rank(v: DFIVersion) -> int:
    """Total ordering for min/max_version comparisons."""
    return _VERSION_RANK[v]


@dataclass(frozen=True)
class SignalSpec:
    """One DFI signal's portability profile.

    ``name`` is without the ``dfi_`` prefix — the BFM joins them.
    ``width_key`` names a width category resolved against the
    constructor's per-instance width arguments at BFM init time.
    ``min_version`` is the earliest DFI revision defining the signal;
    ``max_version`` (optional) the last revision it appears in — set
    when a signal is removed or renamed. Renames are two entries: old
    name with ``max_version``, new name with ``min_version``.
    ``memory_types`` is the set of technologies where the signal is
    meaningful (empty frozenset = all).
    """

    name: str
    direction: SignalDirection
    width_key: str
    sub_interface: SubInterface
    min_version: DFIVersion
    memory_types: FrozenSet[MemoryType]
    description: str
    max_version: Optional[DFIVersion] = None

    def applies(self, version: DFIVersion, memory_type: MemoryType) -> bool:
        """Should this signal be present for (version, memory)?"""
        if version_rank(version) < version_rank(self.min_version):
            return False
        if (self.max_version is not None
                and version_rank(version) > version_rank(self.max_version)):
            return False
        if self.memory_types and memory_type not in self.memory_types:
            return False
        return True
