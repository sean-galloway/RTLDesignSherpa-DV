# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR PHY Interface (DFI) BFMs (issue #16).

Public API:

- :class:`DFIVersion`, :class:`MemoryType`, :class:`SubInterface` —
  enums for the version/memory/sub-interface envelope
- :class:`DFIControlPacket`, :class:`DFIWriteDataPacket`,
  :class:`DFIReadDataPacket` — per-sub-interface transaction types
- :class:`DRAMCommand` — high-level DRAM command codes
- :func:`control_field_config`, :func:`write_data_field_config`,
  :func:`read_data_field_config` — packet field configs for the BFMs
- :func:`signals_for`, :func:`required_signal_names`,
  :func:`optional_signal_names` — signal-envelope helpers

The actual BFM classes (DFIMasterMC, DFISlavePHY, DFIMonitor) land in
the next commit; this module ships the foundation (signal envelope,
packet types, field configs) plus Tier 1 unit tests.
"""

from .dfi_base import DFIBase
from .dfi_phase_adapter import (
    DFIPhaseAdapter,
    VALID_PHASE_COUNTS,
    phase_act,
    phase_nop,
    phase_pre,
    phase_rd,
    phase_ref,
    phase_wr,
    phase_wrdata,
)
from .dfi_field_configs import (
    command_field_config,
    read_data_field_config,
    write_data_field_config,
)
from .dfi_master_mc import DFIMasterMC
from .dfi_monitor import DFIMonitor
from .dfi_slave_phy import DFISlavePHY
from .dram_state import (
    AddressMapping,
    Bank,
    BankState,
    DramStateModel,
    ViolationCategory,
    ViolationPolicy,
)
from .jedec_timings import JedecTimings, builtin_timings, load_timings, ns_to_cycles
from .dfi_packet import (
    DFIControlPacket,
    DFIReadDataPacket,
    DFIWriteDataPacket,
    DRAMCommand,
)
from .dfi_signals import (
    SUPPORTED_MEMORY_BY_VERSION,
    DFIVersion,
    MemoryType,
    SignalDirection,
    SignalSpec,
    SubInterface,
    is_supported_pair,
    optional_signal_names,
    required_signal_names,
    signals_for,
    validate_configuration,
)

__all__ = [
    "DFIPhaseAdapter",
    "VALID_PHASE_COUNTS",
    "phase_act",
    "phase_nop",
    "phase_pre",
    "phase_rd",
    "phase_ref",
    "phase_wr",
    "phase_wrdata",
    "DFIVersion",
    "MemoryType",
    "SubInterface",
    "SignalDirection",
    "SignalSpec",
    "DFIControlPacket",
    "DFIWriteDataPacket",
    "DFIReadDataPacket",
    "DRAMCommand",
    "command_field_config",
    "write_data_field_config",
    "read_data_field_config",
    "signals_for",
    "required_signal_names",
    "optional_signal_names",
    "validate_configuration",
    "is_supported_pair",
    "SUPPORTED_MEMORY_BY_VERSION",
    "DFIBase",
    "DFIMasterMC",
    "DFIMonitor",
    "DFISlavePHY",
    "AddressMapping",
    "Bank",
    "BankState",
    "DramStateModel",
    "ViolationCategory",
    "ViolationPolicy",
    "JedecTimings",
    "builtin_timings",
    "load_timings",
    "ns_to_cycles",
]
