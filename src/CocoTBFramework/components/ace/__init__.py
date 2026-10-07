# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACE Components Package
# Purpose: AXI4-ACE Protocol BFM components for CocoTB verification.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""AXI4-ACE Protocol Components Package

This package provides Bus Functional Models (BFMs) for AXI4-ACE protocol
verification. It extends the AXI4 BFM family with ACE coherent-transaction
signals (ARSNOOP/AWSNOOP) and the three snoop channels (AC/CR/CD).

Components:
- ``AXI4ACEMasterRead`` / ``AXI4ACEMasterWrite``: coherent front-side masters
- ``AXI4ACESnoopSlave`` / ``AXI4ACESnoopMaster``: cache-side and CCU-side
  snoop-channel BFMs
- ``ACEComplianceChecker``: snoop-order and CRRESP validity checker

Randomization and timing managers are out of scope for this initial delivery
and are noted as future work.

Usage:
    from CocoTBFramework.components.ace import (
        create_axi4ace_master_rd,
        create_axi4ace_master_wr,
        create_axi4ace_snoop_slave,
        create_axi4ace_snoop_master,
        ACEComplianceChecker,
    )

    master_rd = create_axi4ace_master_rd(dut, clock, prefix="m_axi_",
                                          data_width=64, id_width=4)
"""

# Compliance checking
from .ace_compliance_checker import (
    ACEComplianceChecker,
    ACEViolation,
    ACEViolationType,
)

# Factory functions
from .ace_factories import (
    create_axi4ace_master_interface,
    create_axi4ace_master_rd,
    create_axi4ace_master_wr,
    create_axi4ace_snoop_interface,
    create_axi4ace_snoop_master,
    create_axi4ace_snoop_slave,
    create_complete_axi4ace_testbench_components,
)

# Field configuration helpers
from .ace_field_configs import (
    AXI4ACEFieldConfigHelper,
    create_channel_field_config,
    get_axi4ace_field_configs,
)

# Interface classes
from .ace_interfaces import (
    AXI4ACEMasterRead,
    AXI4ACEMasterWrite,
    AXI4ACESnoopMaster,
    AXI4ACESnoopSlave,
    SnoopResult,
)

# Packet classes and helpers
from .ace_packet import (
    ACEPacket,
    SnoopPacket,
    create_simple_read_packet,
    create_simple_write_packet,
    create_snoop_address_packet,
    create_snoop_data_packet,
    create_snoop_response_packet,
)

# Transaction / CRRESP helpers
from .ace_transaction import (
    CRRESP,
    ACETransactionType,
    CacheState,
    CRRESPBit,
    SnoopType,
)

__all__ = [
    # Field configs
    "AXI4ACEFieldConfigHelper",
    "get_axi4ace_field_configs",
    "create_channel_field_config",

    # Interfaces
    "AXI4ACEMasterRead",
    "AXI4ACEMasterWrite",
    "AXI4ACESnoopSlave",
    "AXI4ACESnoopMaster",
    "SnoopResult",

    # Factories
    "create_axi4ace_master_rd",
    "create_axi4ace_master_wr",
    "create_axi4ace_snoop_slave",
    "create_axi4ace_snoop_master",
    "create_axi4ace_master_interface",
    "create_axi4ace_snoop_interface",
    "create_complete_axi4ace_testbench_components",

    # Packets
    "ACEPacket",
    "SnoopPacket",
    "create_simple_read_packet",
    "create_simple_write_packet",
    "create_snoop_address_packet",
    "create_snoop_response_packet",
    "create_snoop_data_packet",

    # Transactions
    "ACETransactionType",
    "SnoopType",
    "CRRESP",
    "CRRESPBit",
    "CacheState",

    # Compliance
    "ACEComplianceChecker",
    "ACEViolation",
    "ACEViolationType",
]
