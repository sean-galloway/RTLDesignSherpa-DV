# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI signal envelope by version and memory type (issue #16).

The DDR PHY Interface specification defines a different signal set
depending on:

1. The DFI **version** (2.1, 3.x, 4.0, 5.x, 6.0). Signal lifecycles
   are encoded per signal as ``min_version`` / ``max_version`` in the
   catalog — later revisions both add signals AND remove/rename them
   (the v3.0 training redesign, the v4.0 ``*_cs_n`` → ``*_cs`` sweep,
   the v5.x training removal, the v6.0 command-bus repack).

2. The **memory type** the system targets. ``dfi_reset_n`` exists only
   for DDR3+; ``dfi_odt`` for DDR2/3/4 + LPDDR3; ``dfi_rddata_dnv``
   only for LPDDR2; etc.

3. The **sub-interface profile** the user opts into. Which
   sub-interfaces exist at all is itself version-dependent — see
   :data:`SUB_INTERFACES_BY_VERSION`.

This module is the public API; the per-signal data lives in
``dfi_signal_catalog`` and the shared types in ``dfi_signal_types``
(both re-exported here).

Source: the actual specification PDFs — DFI v2.1.1 (Denali, 2010),
v3.1, v4.0, v5.2, v6.0 (Cadence) — transcribed table-by-table from
chapter 3 "Interface Signal Groups" of each. See the catalog module
docstring for the per-version table references.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Tuple

from .dfi_signal_catalog import ALL_SIGNALS  # noqa: F401
from .dfi_signal_types import (  # noqa: F401  (public re-exports)
    WIDTH_ADDR,
    WIDTH_ALERT,
    WIDTH_BANK,
    WIDTH_BANK_GROUP,
    WIDTH_CHIP_ID,
    WIDTH_CS,
    WIDTH_CS_X_DATA_EN,
    WIDTH_CTRL,
    WIDTH_DATA,
    WIDTH_DATA_DIV8,
    WIDTH_DATA_EN,
    WIDTH_EIGHT_BITS,
    WIDTH_FIVE_BITS,
    WIDTH_ONE_BIT,
    WIDTH_PER_SLICE,
    WIDTH_RANK,
    WIDTH_RD_VALID,
    WIDTH_SIX_BITS,
    WIDTH_SIXTEEN_BITS,
    WIDTH_THREE_BITS,
    WIDTH_TWO_BITS,
    WIDTH_WCK,
    DFIVersion,
    MemoryType,
    SignalDirection,
    SignalSpec,
    SubInterface,
    version_rank,
)

# ----------------------------------------------------------------------
# Per-version support matrices
# ----------------------------------------------------------------------

# Memory-type support by revision. Sources: each spec's overview +
# revision history. v3.0 added DDR4; v3.1 added LPDDR3; v4.0 added
# LPDDR4; v5.x added DDR5 + LPDDR5 (legacy kept); v6.0 dropped DDR1-4
# and LPDDR1-4 and added LPDDR6 + HBM4.
SUPPORTED_MEMORY_BY_VERSION: Dict[DFIVersion, FrozenSet[MemoryType]] = {
    DFIVersion.V2_1: frozenset({
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3,
        MemoryType.LPDDR1, MemoryType.LPDDR2,
    }),
    DFIVersion.V3_1: frozenset({
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3,
    }),
    DFIVersion.V4_0: frozenset({
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3,
        MemoryType.LPDDR4,
    }),
    DFIVersion.V5_2: frozenset({
        MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4,
        MemoryType.DDR5,
        MemoryType.LPDDR1, MemoryType.LPDDR2, MemoryType.LPDDR3,
        MemoryType.LPDDR4, MemoryType.LPDDR5,
    }),
    DFIVersion.V6_0: frozenset({
        MemoryType.DDR5, MemoryType.LPDDR5, MemoryType.LPDDR6,
        MemoryType.HBM4,
    }),
}


# Sub-interface availability by revision (chapter-3 structure of each
# spec). TRAINING/DB_TRAINING end at v4.0 (v5.x: training is
# PHY-internal); DISCONNECT ends at v5.x (v6.0 removed it).
SUB_INTERFACES_BY_VERSION: Dict[DFIVersion, FrozenSet[SubInterface]] = {
    DFIVersion.V2_1: frozenset({
        SubInterface.COMMAND, SubInterface.WRITE_DATA,
        SubInterface.READ_DATA, SubInterface.UPDATE, SubInterface.STATUS,
        SubInterface.TRAINING, SubInterface.LOW_POWER,
    }),
    DFIVersion.V3_1: frozenset({
        SubInterface.COMMAND, SubInterface.WRITE_DATA,
        SubInterface.READ_DATA, SubInterface.UPDATE, SubInterface.STATUS,
        SubInterface.TRAINING, SubInterface.LOW_POWER, SubInterface.ERROR,
    }),
    DFIVersion.V4_0: frozenset({
        SubInterface.COMMAND, SubInterface.WRITE_DATA,
        SubInterface.READ_DATA, SubInterface.UPDATE, SubInterface.STATUS,
        SubInterface.TRAINING, SubInterface.DB_TRAINING,
        SubInterface.LOW_POWER, SubInterface.ERROR,
        SubInterface.PHY_MANAGED, SubInterface.DISCONNECT,
    }),
    DFIVersion.V5_2: frozenset({
        SubInterface.COMMAND, SubInterface.WRITE_DATA,
        SubInterface.READ_DATA, SubInterface.UPDATE, SubInterface.STATUS,
        SubInterface.LOW_POWER, SubInterface.ERROR,
        SubInterface.PHY_MANAGED, SubInterface.DISCONNECT,
        SubInterface.MC_TO_PHY_MSG, SubInterface.WCK_CONTROL,
    }),
    DFIVersion.V6_0: frozenset({
        SubInterface.COMMAND, SubInterface.WRITE_DATA,
        SubInterface.READ_DATA, SubInterface.UPDATE, SubInterface.STATUS,
        SubInterface.LOW_POWER, SubInterface.ERROR,
        SubInterface.PHY_MANAGED, SubInterface.MC_TO_PHY_MSG,
        SubInterface.WCK_CONTROL,
    }),
}


# Default sub-interface profile: the three the BFM wires end-to-end
# (command + write data + read data). Handshake-level areas (update,
# status, low power, error, PHY managed, ...) are driven through the
# BFM's set_* primitives and behavior classes — opt into their signal
# envelopes by passing an explicit ``sub_interfaces`` set.
DEFAULT_SUB_INTERFACES: FrozenSet[SubInterface] = frozenset({
    SubInterface.COMMAND,
    SubInterface.WRITE_DATA,
    SubInterface.READ_DATA,
})

# Backward-compatible aliases (pre-spec-verification API). The "MVP"
# phase gating is gone — every version/memory in the matrices above
# is buildable — but downstream code imports these names.
MVP_SUB_INTERFACES = DEFAULT_SUB_INTERFACES
MVP_VERSIONS: FrozenSet[DFIVersion] = frozenset(DFIVersion)
MVP_MEMORY_TYPES: FrozenSet[MemoryType] = frozenset(MemoryType)


# ----------------------------------------------------------------------
# Envelope resolution
# ----------------------------------------------------------------------


def signals_for(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
) -> Tuple[SignalSpec, ...]:
    """Return the signal specs that apply for the given configuration.

    ``sub_interfaces`` defaults to :data:`DEFAULT_SUB_INTERFACES`
    (command + write_data + read_data). Pass an explicit set to opt
    into more (or fewer) channels.
    """
    if sub_interfaces is None:
        sub_interfaces = DEFAULT_SUB_INTERFACES
    return tuple(
        s for s in ALL_SIGNALS
        if s.sub_interface in sub_interfaces
        and s.applies(version, memory_type)
    )


def required_signal_names(
    version: DFIVersion,
    memory_type: MemoryType,
    sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
    prefix: str = "dfi",
) -> List[str]:
    """Return the **always-present** signal names for
    ``cocotb_bus.BusDriver`` / ``BusMonitor`` ``_signals`` lists.
    Names include the ``<prefix>_`` prefix to match DUT port names.

    Universal signals (empty ``memory_types``) go here.
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

    Signals gated on memory_type (odt, reset_n, dnv, ...) go here so
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
    """Raise ``ValueError`` for configurations the spec doesn't define.

    1. ``(version, memory_type)`` must be a valid pair per
       :data:`SUPPORTED_MEMORY_BY_VERSION` (e.g. DDR5 needs v5.x+;
       DDR3 died with v5.x).
    2. Every requested sub-interface must exist at that version per
       :data:`SUB_INTERFACES_BY_VERSION` (e.g. TRAINING is v2.1-v4.0
       only; WCK_CONTROL needs v5.x+).
    """
    supported = SUPPORTED_MEMORY_BY_VERSION[version]
    if memory_type not in supported:
        raise ValueError(
            f"DFI {version.value} does not support memory type "
            f"{memory_type.value}. Per spec, v{version.value} supports "
            f"{sorted(m.value for m in supported)}."
        )
    available = SUB_INTERFACES_BY_VERSION[version]
    unavailable = sub_interfaces - available
    if unavailable:
        raise ValueError(
            f"Sub-interface(s) {sorted(s.value for s in unavailable)} do "
            f"not exist in DFI {version.value}. Available at this "
            f"version: {sorted(s.value for s in available)}."
        )


def is_supported_pair(version: DFIVersion, memory_type: MemoryType) -> bool:
    """True if the spec defines support for ``memory_type`` at
    ``version``. See :data:`SUPPORTED_MEMORY_BY_VERSION`.
    """
    return memory_type in SUPPORTED_MEMORY_BY_VERSION.get(version, frozenset())
