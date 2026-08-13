# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DDR PHY Interface (DFI) BFMs (issue #16).

Public API:

- :class:`DFIVersion`, :class:`MemoryType`, :class:`SubInterface` —
  enums for the version/memory/sub-interface envelope
- :class:`DFIControlPacket`, :class:`DFIWriteDataPacket`,
  :class:`DFIReadDataPacket` — per-sub-interface transaction types
- :class:`DRAMCommand` — high-level DRAM command codes
- :func:`command_field_config`, :func:`write_data_field_config`,
  :func:`read_data_field_config` — packet field configs for the BFMs
- :func:`signals_for`, :func:`required_signal_names`,
  :func:`optional_signal_names` — signal-envelope helpers
- :class:`DFIBase`, :class:`DFIMasterMC`, :class:`DFISlavePHY`,
  :class:`DFIMonitor` — the BFM chassis and the three BFM roles
- :class:`DramStateModel`, :class:`AddressMapping`,
  :class:`JedecTimings` — DRAM state / address / timing models
"""

from .ca_map import (
    HBM4_COL_CA_MAP,
    HBM4_ROW_CA_MAP,
    CACodec,
    CAMap,
    camap_from_dict,
)
from .ca_transport import (
    LPDDR5_CA_WIDTH,
    LPDDR6_CA_WIDTH,
    CAPhases,
    pack_ddr_cmdaddr,
    unpack_ddr_cmdaddr,
)
from .ddr5_ca_map import DDR5_CA_MAP, DDR5_CA_WIDTH
from .dfi_base import DFIBase
from .dfi_compliance import (
    DFIComplianceChecker,
    DFIComplianceParams,
)
from .dfi_field_configs import (
    command_field_config,
    read_data_field_config,
    write_data_field_config,
)
from .dfi_master_mc import DFIMasterMC
from .dfi_monitor import DFIMonitor
from .dfi_packet import (
    DFIControlPacket,
    DFIReadDataPacket,
    DFIWriteDataPacket,
    DRAMCommand,
)
from .dfi_phase_adapter import (
    VALID_PHASE_COUNTS,
    DFIPhaseAdapter,
    phase_act,
    phase_nop,
    phase_pre,
    phase_rd,
    phase_ref,
    phase_wr,
    phase_wrdata,
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
from .dfi_slave_phy import DFISlavePHY
from .dram_state import (
    AddressMapping,
    Bank,
    BankState,
    DramStateModel,
    ViolationCategory,
    ViolationPolicy,
)
from .hbm4_commands import (
    ColumnCommand,
    RowCommand,
    decode_col_pair,
    decode_row_act_sequence,
    decode_row_edge,
    encode_col_mrs,
    encode_col_rd,
    encode_col_wr,
    encode_row_act,
)
from .hbm_ca import (
    HBM4_CMDADDR_WIDTH,
    HBM4CAEdge,
    HBM4CAWord,
    pack_hbm4_cmdaddr,
    unpack_hbm4_cmdaddr,
)
from .jedec_timings import JedecTimings, builtin_timings, load_timings, ns_to_cycles
from .lpddr5_ca_map import (
    LPDDR5_CA_MAP_8B,
    LPDDR5_CA_MAP_16B,
    LPDDR5_CA_MAP_BG,
    lpddr5_ca_map,
)
from .lpddr6_ca_map import LPDDR6_CA_MAP

__all__ = [
    "CACodec",
    "CAMap",
    "HBM4_COL_CA_MAP",
    "HBM4_ROW_CA_MAP",
    "camap_from_dict",
    "CAPhases",
    "DDR5_CA_MAP",
    "DDR5_CA_WIDTH",
    "LPDDR5_CA_WIDTH",
    "LPDDR6_CA_WIDTH",
    "LPDDR5_CA_MAP_8B",
    "LPDDR5_CA_MAP_16B",
    "LPDDR5_CA_MAP_BG",
    "LPDDR6_CA_MAP",
    "lpddr5_ca_map",
    "pack_ddr_cmdaddr",
    "unpack_ddr_cmdaddr",
    "ColumnCommand",
    "RowCommand",
    "decode_col_pair",
    "decode_row_act_sequence",
    "decode_row_edge",
    "encode_col_mrs",
    "encode_col_rd",
    "encode_col_wr",
    "encode_row_act",
    "HBM4_CMDADDR_WIDTH",
    "HBM4CAEdge",
    "HBM4CAWord",
    "pack_hbm4_cmdaddr",
    "unpack_hbm4_cmdaddr",
    "DFIComplianceChecker",
    "DFIComplianceParams",
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
