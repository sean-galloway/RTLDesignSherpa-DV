# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI signal envelope by version and memory type (issue #16).

The DDR PHY Interface specification defines a different signal set
depending on:

1. The DFI **version** (2.1, 3.1, 4.0, 5.2, 6.0). Each new revision is
   strictly **additive** — later versions add signals, they don't remove
   them. A small handful of signals have semantic shifts across versions
   (handled in the BFM, not here).

2. The **memory type** the system targets. ``dfi_reset_n`` exists only for
   DDR3+; ``dfi_odt`` only for DDR2/DDR3; ``dfi_rddata_dnv`` only for
   LPDDR2; etc.

3. The **sub-interface profile** the user opts into. The framework
   supports six sub-interfaces (control, write_data, read_data, update,
   status, training) and the MVP wires up the first three.

This module encodes that envelope as data so the BFM constructor can
build a per-instance signal list without scattered ``if version >=``
checks in the driver code.

Source: DFI v2.1 spec (Denali Software, Jan 2009, cleartext), Tables
2-11 (pages 9-22). The v3-v6 entries below are populated as the
corresponding spec PDFs become decryptable; today they fall back to
the v2.1 envelope, which is a strict subset.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------


class DFIVersion(str, Enum):
    """Supported DFI specification revisions."""

    V2_1 = "2.1"
    V3_1 = "3.1"
    V4_0 = "4.0"
    V5_2 = "5.2"


class MemoryType(str, Enum):
    """DRAM memory technologies the DFI can target.

    Scope: DDR1-5 + LPDDR1-5. v6.0 dropped DDR/2/3/4 + LPDDR/1/2/3/4
    and added LPDDR6 / HBM4 — that's out of scope for this BFM
    generation. See ``docs/internal/dfi-semantic-shifts.md`` for the
    rationale and the memory note on v6 scope changes for the research.
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


class SubInterface(str, Enum):
    """The DFI sub-interfaces (scope: v2.1-v5.x).

    v2.1 had six (the first six below plus TRAINING). v5.x grew this
    to roughly a dozen as new functions split out across revisions.
    MVP wires up COMMAND + WRITE_DATA + READ_DATA; Phase 2/3 add the
    rest within this version range.

    Naming note: v2.1 called the command interface "Control Interface";
    later revisions renamed it to "Command Interface" alongside the
    ``dfi_address`` → ``dfi_cmdaddr`` signal rename. We use the later
    name.
    """

    # v2.1 baseline (plus the v2.1-only TRAINING below)
    COMMAND = "command"          # was "control" in v2.1
    WRITE_DATA = "write_data"
    READ_DATA = "read_data"
    STATUS = "status"
    UPDATE = "update"

    # v3.0+
    DBI = "dbi"                  # Data Bus Inversion
    ECC = "ecc"
    LINK_CRC = "link_crc"        # Link DQ CRC

    # v3.1+
    LOW_POWER = "low_power"      # split from Status

    # v4.0+
    PHY_MANAGED = "phy_managed"  # added as "PHY Master Interface", renamed v5.2

    # v5.x+
    WCK_CONTROL = "wck_control"  # DDR5/LPDDR5 WCK
    MC_TO_PHY_MSG = "mc_to_phy_msg"
    PHY_ERROR = "phy_error"

    # Multi-channel (LPDDR-class)
    MULTI_CHANNEL = "multi_channel"

    # v2.1+ training sub-interface
    TRAINING = "training"


class SignalDirection(str, Enum):
    """Direction of a DFI signal from the MC's point of view."""

    MC_TO_PHY = "mc_to_phy"
    PHY_TO_MC = "phy_to_mc"


# Per-version memory-type support matrix. Source: revision history of
# each spec. v3.x onward this is purely additive within the v2.1-v5.x
# scope window — v6.0 (out of scope) is where the spec drops legacy
# DDR support, which is why this BFM generation stops at v5.x.
SUPPORTED_MEMORY_BY_VERSION: Dict[DFIVersion, FrozenSet[MemoryType]] = {
    DFIVersion.V2_1: frozenset({
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3,
        MemoryType.LPDDR1, MemoryType.LPDDR2,
    }),
    DFIVersion.V3_1: frozenset({
        # v3.0 added DDR4; v3.1 added LPDDR3
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3,
    }),
    DFIVersion.V4_0: frozenset({
        # v4.0 added LPDDR4
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3, MemoryType.LPDDR4,
    }),
    DFIVersion.V5_2: frozenset({
        # v5.x added DDR5, LPDDR5; legacy still supported
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4, MemoryType.DDR5,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3,
        MemoryType.LPDDR4, MemoryType.LPDDR5,
    }),
}


# What the MVP envelope covers. These shrink the spec's actual support
# matrix down to what the BFM has signal-table coverage for today.
# Phase 2 widens MVP_VERSIONS / MVP_MEMORY_TYPES; Phase 3 widens
# MVP_SUB_INTERFACES.
MVP_VERSIONS: FrozenSet[DFIVersion] = frozenset({DFIVersion.V2_1})
MVP_MEMORY_TYPES: FrozenSet[MemoryType] = frozenset({
    MemoryType.DDR1,
    MemoryType.DDR2,
    MemoryType.DDR3,
    MemoryType.LPDDR1,
    MemoryType.LPDDR2,
})
MVP_SUB_INTERFACES: FrozenSet[SubInterface] = frozenset({
    SubInterface.COMMAND,
    SubInterface.WRITE_DATA,
    SubInterface.READ_DATA,
})


# ----------------------------------------------------------------------
# Signal specification
# ----------------------------------------------------------------------


# Width keywords resolved at BFM construction time from the user's
# width parameters. The strings here are sentinels; the resolver maps
# them to concrete ints.
WIDTH_ADDR = "addr_width"
WIDTH_BANK = "bank_width"
WIDTH_CS = "cs_width"
WIDTH_CTRL = "ctrl_width"
WIDTH_DATA = "data_width"
WIDTH_DATA_EN = "data_enable_width"
WIDTH_RD_VALID = "rd_valid_width"
WIDTH_DATA_DIV8 = "data_width_div_8"  # for masks / dnv
WIDTH_ONE_BIT = "one_bit"
WIDTH_TWO_BITS = "two_bits"


@dataclass(frozen=True)
class SignalSpec:
    """One DFI signal's portability profile.

    ``name`` is without the ``dfi_`` prefix — the BFM joins them.
    ``width_key`` names a width category that gets resolved against
    the constructor's per-instance width arguments at BFM init time.
    ``min_version`` is the earliest DFI revision that introduced the
    signal. ``max_version`` (optional) is the last revision in which
    it appeared — set when a signal gets removed or renamed; leave as
    ``None`` if it's still in the current spec. ``memory_types`` is the
    set of memory technologies where this signal is meaningful (an empty
    frozenset means "all").

    Renames across versions (e.g. ``dfi_address`` → ``dfi_cmdaddr``)
    are encoded as two SignalSpec entries: the old name with
    ``max_version`` set, and the new name with ``min_version`` set to
    the version that introduced the rename.
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
        """Should this signal be present for the given (version, memory)?"""
        if _version_rank(version) < _version_rank(self.min_version):
            return False
        if self.max_version is not None and _version_rank(version) > _version_rank(self.max_version):
            return False
        if self.memory_types and memory_type not in self.memory_types:
            return False
        return True


def _version_rank(v: DFIVersion) -> int:
    """Ordering for ``min_version`` comparisons."""
    return {
        DFIVersion.V2_1: 21,
        DFIVersion.V3_1: 31,
        DFIVersion.V4_0: 40,
        DFIVersion.V5_2: 52,
    }[v]


# ----------------------------------------------------------------------
# v2.1 signal catalog (from Tables 2, 4, 6 — pages 9-14 of the spec)
# ----------------------------------------------------------------------

# Convenience aliases for memory-type frozensets used below.
_ALL: FrozenSet[MemoryType] = frozenset()  # empty = applies to all memory types
_DDR1_LPDDR1_DDR2_DDR3: FrozenSet[MemoryType] = frozenset({
    MemoryType.DDR1, MemoryType.LPDDR1, MemoryType.DDR2, MemoryType.DDR3,
})
_DDR2_DDR3: FrozenSet[MemoryType] = frozenset({MemoryType.DDR2, MemoryType.DDR3})
_DDR3_ONLY: FrozenSet[MemoryType] = frozenset({MemoryType.DDR3})
_LPDDR2_ONLY: FrozenSet[MemoryType] = frozenset({MemoryType.LPDDR2})


# Command (a.k.a. "Control") Interface — DFI v2.1 Table 2 (pages 9-10).
# v2.1 called this the "Control Interface" with bus ``dfi_address``;
# later revisions renamed to "Command Interface" with ``dfi_cmdaddr``.
# Same logical role.
_COMMAND_SIGNALS: Tuple[SignalSpec, ...] = (
    SignalSpec(
        name="address",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_ADDR,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI address bus (LPDDR2: 20-bit CA bus via Table 1)",
    ),
    SignalSpec(
        name="bank",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_BANK,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI bank bus; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="cas_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI column address strobe; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="cke",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI clock enable (reset polarity is memory-defined)",
    ),
    SignalSpec(
        name="cs_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI chip select",
    ),
    SignalSpec(
        name="odt",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR2_DDR3,
        description="DFI on-die termination control (DDR2/DDR3 only)",
    ),
    SignalSpec(
        name="ras_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI row address strobe; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="reset_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR3_ONLY,
        description="DFI reset (DDR3 only)",
    ),
    SignalSpec(
        name="we_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI write enable; LPDDR2 holds idle",
    ),
)


# Write Data Interface — DFI v2.1 Table 4 (page 11-12)
_WRITE_DATA_SIGNALS: Tuple[SignalSpec, ...] = (
    SignalSpec(
        name="wrdata",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_DATA,
        sub_interface=SubInterface.WRITE_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Write data; begins 1 cycle after wrdata_en assertion",
    ),
    SignalSpec(
        name="wrdata_en",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_DATA_EN,
        sub_interface=SubInterface.WRITE_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Write data enable; asserted t_phy_wrlat cycles after write cmd",
    ),
    SignalSpec(
        name="wrdata_mask",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_DATA_DIV8,
        sub_interface=SubInterface.WRITE_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Byte mask for wrdata; 1 bit per 8 wrdata bits",
    ),
)


# Read Data Interface — DFI v2.1 Table 6 (page 14)
_READ_DATA_SIGNALS: Tuple[SignalSpec, ...] = (
    SignalSpec(
        name="rddata",
        direction=SignalDirection.PHY_TO_MC,
        width_key=WIDTH_DATA,
        sub_interface=SubInterface.READ_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Read data; valid when rddata_valid asserts",
    ),
    SignalSpec(
        name="rddata_en",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_DATA_EN,
        sub_interface=SubInterface.READ_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Read data enable; asserted t_rddata_en after read cmd",
    ),
    SignalSpec(
        name="rddata_valid",
        direction=SignalDirection.PHY_TO_MC,
        width_key=WIDTH_RD_VALID,
        sub_interface=SubInterface.READ_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="Read data valid; asserted with rddata, max t_phy_rdlat after rddata_en",
    ),
    SignalSpec(
        name="rddata_dnv",
        direction=SignalDirection.PHY_TO_MC,
        width_key=WIDTH_DATA_DIV8,
        sub_interface=SubInterface.READ_DATA,
        min_version=DFIVersion.V2_1,
        memory_types=_LPDDR2_ONLY,
        description="Data-not-valid (LPDDR2 only); byte-granular",
    ),
)


# All signals across the catalog. Phase 2 adds update/status/training.
_ALL_SIGNALS: Tuple[SignalSpec, ...] = (
    _COMMAND_SIGNALS + _WRITE_DATA_SIGNALS + _READ_DATA_SIGNALS
)


# ----------------------------------------------------------------------
# Public API: envelope resolution
# ----------------------------------------------------------------------


def signals_for(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
) -> Tuple[SignalSpec, ...]:
    """Return the signal specs that apply for the given configuration.

    ``sub_interfaces`` defaults to the MVP set (control + write_data +
    read_data). Pass an explicit set to opt into more (or fewer) channels.
    """
    if sub_interfaces is None:
        sub_interfaces = MVP_SUB_INTERFACES
    return tuple(
        s for s in _ALL_SIGNALS
        if s.sub_interface in sub_interfaces and s.applies(version, memory_type)
    )


def required_signal_names(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
    prefix: str = "dfi",
) -> List[str]:
    """Return the **always-present** signal names for ``cocotb_bus.BusDriver``
    / ``BusMonitor`` ``_signals`` lists. Names include the ``<prefix>_``
    prefix so they match the DUT port names.

    Universal signals (memory_types is empty / all types) go here.
    """
    return [
        f"{prefix}_{s.name}"
        for s in signals_for(version, memory_type, sub_interfaces)
        if not s.memory_types  # universal
    ]


def optional_signal_names(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
    prefix: str = "dfi",
) -> List[str]:
    """Return the **conditionally-present** signal names.

    Signals gated on memory_type (odt, reset_n, dnv, etc.) go here so
    ``cocotb_bus`` doesn't error when the DUT lacks them.
    """
    return [
        f"{prefix}_{s.name}"
        for s in signals_for(version, memory_type, sub_interfaces)
        if s.memory_types  # memory-type gated
    ]


def validate_configuration(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: FrozenSet[SubInterface],
) -> None:
    """Raise ``ValueError`` for unsupported configurations.

    Validates in this order:

    1. ``version`` is in the MVP set (Phase 2 widens this).
    2. ``memory_type`` is in the MVP set (Phase 2 widens this).
    3. ``(version, memory_type)`` is a valid pair per the spec —
       :data:`SUPPORTED_MEMORY_BY_VERSION` is the canonical source.
    4. All requested sub-interfaces are in the MVP set.
    """
    if version not in MVP_VERSIONS:
        raise ValueError(
            f"DFI BFM MVP only supports {sorted(v.value for v in MVP_VERSIONS)}; "
            f"got {version.value}. Phase 2 will add v3.1/v4.0/v5.2 envelopes."
        )
    if memory_type not in MVP_MEMORY_TYPES:
        raise ValueError(
            f"DFI BFM MVP only supports memory types "
            f"{sorted(m.value for m in MVP_MEMORY_TYPES)}; got {memory_type.value}. "
            f"Phase 2 will add DDR4/DDR5/LPDDR3/LPDDR4/LPDDR5."
        )
    supported = SUPPORTED_MEMORY_BY_VERSION[version]
    if memory_type not in supported:
        raise ValueError(
            f"DFI {version.value} does not support memory type {memory_type.value}. "
            f"Per spec, v{version.value} supports "
            f"{sorted(m.value for m in supported)}."
        )
    unsupported = sub_interfaces - MVP_SUB_INTERFACES
    if unsupported:
        raise ValueError(
            f"DFI BFM MVP only supports sub-interfaces "
            f"{sorted(s.value for s in MVP_SUB_INTERFACES)}; "
            f"got {sorted(s.value for s in unsupported)} which are Phase 2/3."
        )


def is_supported_pair(version: DFIVersion, memory_type: MemoryType) -> bool:
    """Return True if the spec defines support for ``memory_type`` at
    ``version``. See :data:`SUPPORTED_MEMORY_BY_VERSION`.
    """
    return memory_type in SUPPORTED_MEMORY_BY_VERSION.get(version, frozenset())
