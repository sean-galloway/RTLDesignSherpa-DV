# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI3 Components Package
# Purpose: AXI3 Protocol BFM components for CocoTB verification.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""AXI3 Protocol Components Package.

This package provides Bus Functional Models (BFMs) for AXI3 protocol
verification.  AXI3 is implemented as a standalone protocol family:

* AWLEN/ARLEN are 4 bits (1-16 beats per burst).
* AWLOCK/ARLOCK are 2 bits (normal / exclusive / locked).
* QoS and REGION signals do not exist.
* The W channel carries WID, making write-data interleaving legal.

Usage:
    from CocoTBFramework.components.axi3 import (
        create_axi3_master_rd,
        create_axi3_master_wr,
        create_axi3_slave_rd,
        create_axi3_slave_wr,
        AXI3Packet,
        create_simple_write_packets,
        create_simple_read_packet,
    )
"""

from .axi3_factories import (
    create_axi3_master_interface,
    create_axi3_master_rd,
    create_axi3_master_wr,
    create_axi3_slave_interface,
    create_axi3_slave_rd,
    create_axi3_slave_wr,
    create_complete_axi3_testbench_components,
)
from .axi3_field_configs import (
    AXI3FieldConfigHelper,
    create_channel_field_config,
    get_axi3_field_configs,
)
from .axi3_interfaces import (
    AXI3MasterRead,
    AXI3MasterWrite,
    AXI3SlaveRead,
    AXI3SlaveWrite,
)
from .axi3_packet import (
    AXI3Packet,
    create_simple_read_packet,
    create_simple_write_packets,
)

__all__ = [
    # Field configuration
    "AXI3FieldConfigHelper",
    "create_channel_field_config",
    "get_axi3_field_configs",
    # Interface classes
    "AXI3MasterRead",
    "AXI3MasterWrite",
    "AXI3SlaveRead",
    "AXI3SlaveWrite",
    # Packet
    "AXI3Packet",
    "create_simple_read_packet",
    "create_simple_write_packets",
    # Factories
    "create_axi3_master_interface",
    "create_axi3_master_rd",
    "create_axi3_master_wr",
    "create_axi3_slave_interface",
    "create_axi3_slave_rd",
    "create_axi3_slave_wr",
    "create_complete_axi3_testbench_components",
]
