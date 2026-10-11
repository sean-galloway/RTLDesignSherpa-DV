# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APB3 Components Package
# Purpose: APB3 Protocol components — APB4 minus PPROT/PSTRB.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""APB3 Protocol Components.

This package provides APB3 BFM support by subclassing the APB4 classes and
removing the optional ``PPROT`` and ``PSTRB`` signals.  ``PSLVERR`` remains
optional, matching AMBA APB3 (rev1) practice.

Usage:
    from CocoTBFramework.components.apb3 import (
        APB3Master, APB3Slave, APB3Monitor, APB3Packet,
        create_apb3_master, create_apb3_slave, create_apb3_monitor,
    )
"""

from .apb3_components import APB3Master, APB3Monitor, APB3Slave
from .apb3_factories import (
    create_apb3_components,
    create_apb3_master,
    create_apb3_monitor,
    create_apb3_slave,
)
from .apb3_packet import APB3Packet

__all__ = [
    'APB3Master',
    'APB3Slave',
    'APB3Monitor',
    'APB3Packet',
    'create_apb3_master',
    'create_apb3_slave',
    'create_apb3_monitor',
    'create_apb3_components',
]
