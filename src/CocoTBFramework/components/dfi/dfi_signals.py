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
from typing import FrozenSet, List, Optional, Tuple

# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------


class DFIVersion(str, Enum):
    """Supported DFI specification revisions."""

    V2_1 = "2.1"
    V3_1 = "3.1"
    V4_0 = "4.0"
    V5_2 = "5.2"
    V6_0 = "6.0"


class MemoryType(str, Enum):
    """DRAM memory technologies the DFI can target."""

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
    """The six DFI sub-interfaces. MVP wires up the first three."""

    CONTROL = "control"
    WRITE_DATA = "write_data"
    READ_DATA = "read_data"
    UPDATE = "update"
    STATUS = "status"
    TRAINING = "training"


class SignalDirection(str, Enum):
    """Direction of a DFI signal from the MC's point of view."""

    MC_TO_PHY = "mc_to_phy"
    PHY_TO_MC = "phy_to_mc"


# What each (version, memory_type) combination supports. Used only for
# friendly error messages; the actual gating logic lives in the
# applies_to_memory predicate on each SignalSpec.
MVP_VERSIONS: FrozenSet[DFIVersion] = frozenset({DFIVersion.V2_1})
MVP_MEMORY_TYPES: FrozenSet[MemoryType] = frozenset({
    MemoryType.DDR1,
    MemoryType.DDR2,
    MemoryType.DDR3,
    MemoryType.LPDDR1,
    MemoryType.LPDDR2,
})
MVP_SUB_INTERFACES: FrozenSet[SubInterface] = frozenset({
    SubInterface.CONTROL,
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
    signal. ``memory_types`` is the set of memory technologies where
    this signal is meaningful (an empty frozenset means "all").
    """

    name: str
    direction: SignalDirection
    width_key: str
    sub_interface: SubInterface
    min_version: DFIVersion
    memory_types: FrozenSet[MemoryType]
    description: str

    def applies(self, version: DFIVersion, memory_type: MemoryType) -> bool:
        """Should this signal be present for the given (version, memory)?"""
        if _version_rank(version) < _version_rank(self.min_version):
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
        DFIVersion.V6_0: 60,
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


# Control Interface — DFI v2.1 Table 2 (page 9-10)
_CONTROL_SIGNALS: Tuple[SignalSpec, ...] = (
    SignalSpec(
        name="address",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_ADDR,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI address bus (LPDDR2: 20-bit CA bus via Table 1)",
    ),
    SignalSpec(
        name="bank",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_BANK,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI bank bus; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="cas_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI column address strobe; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="cke",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI clock enable (reset polarity is memory-defined)",
    ),
    SignalSpec(
        name="cs_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_ALL,
        description="DFI chip select",
    ),
    SignalSpec(
        name="odt",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR2_DDR3,
        description="DFI on-die termination control (DDR2/DDR3 only)",
    ),
    SignalSpec(
        name="ras_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR1_LPDDR1_DDR2_DDR3,
        description="DFI row address strobe; LPDDR2 holds idle",
    ),
    SignalSpec(
        name="reset_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CS,
        sub_interface=SubInterface.CONTROL,
        min_version=DFIVersion.V2_1,
        memory_types=_DDR3_ONLY,
        description="DFI reset (DDR3 only)",
    ),
    SignalSpec(
        name="we_n",
        direction=SignalDirection.MC_TO_PHY,
        width_key=WIDTH_CTRL,
        sub_interface=SubInterface.CONTROL,
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
    _CONTROL_SIGNALS + _WRITE_DATA_SIGNALS + _READ_DATA_SIGNALS
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
    """Raise ``ValueError`` if the requested combination is outside MVP.

    Phase 2 will widen MVP_VERSIONS, MVP_MEMORY_TYPES, and
    MVP_SUB_INTERFACES; this function is the single chokepoint.
    """
    if version not in MVP_VERSIONS:
        raise ValueError(
            f"DFI BFM MVP only supports {sorted(v.value for v in MVP_VERSIONS)}; "
            f"got {version.value}. Phase 2 will add v3.1/v4.0/v5.2/v6.0 envelopes."
        )
    if memory_type not in MVP_MEMORY_TYPES:
        raise ValueError(
            f"DFI BFM MVP only supports memory types "
            f"{sorted(m.value for m in MVP_MEMORY_TYPES)}; got {memory_type.value}. "
            f"Phase 2 will add DDR4/DDR5/LPDDR3/LPDDR4/LPDDR5."
        )
    unsupported = sub_interfaces - MVP_SUB_INTERFACES
    if unsupported:
        raise ValueError(
            f"DFI BFM MVP only supports sub-interfaces "
            f"{sorted(s.value for s in MVP_SUB_INTERFACES)}; "
            f"got {sorted(s.value for s in unsupported)} which are Phase 2."
        )
