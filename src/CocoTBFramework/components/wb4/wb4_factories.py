# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# Module: wb4_factories
# Purpose: One-call creation of the Wishbone B4 BFMs
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-09-09
"""Factory functions for the Wishbone B4 (pipelined) BFMs.

    from CocoTBFramework.components.wb4.wb4_factories import (
        create_wb4_master, create_wb4_slave, create_wb4_monitor)

    slave = create_wb4_slave(dut, "WB Slave", "m_wb", dut.clk, data_width=32)
    mon   = create_wb4_monitor(dut, "WB Mon", "m_wb", dut.clk)

The ``prefix`` is the port-name stem (``m_wb`` binds ``m_wb_CYC``,
``m_wb_STB`` ... case-insensitively; ``DAT_W``/``DAT_O`` and ``DAT_R``/
``DAT_I`` are both accepted).
"""

from ..shared.flex_randomizer import FlexRandomizer
from .wb4_components import WB4Master, WB4Monitor, WB4Slave


def create_wb4_master(dut, title, prefix, clock, addr_width=32, data_width=32,
                      randomizer=None, max_outstanding=8, log=None):
    """A pipelined master. ``randomizer`` key ``stb``: idle clocks between requests."""
    log = log or getattr(dut, '_log', None)
    if randomizer is None:
        randomizer = FlexRandomizer(WB4Master._default_randomizer_constraints())
    return WB4Master(dut, title, prefix, clock, addr_width=addr_width, data_width=data_width,
                     randomizer=randomizer, max_outstanding=max_outstanding, log=log)


def create_wb4_slave(dut, title, prefix, clock, addr_width=32, data_width=32,
                     registers=None, num_lines=1024, randomizer=None,
                     max_outstanding=16, status_hook=None, log=None):
    """A pipelined slave over a MemoryModel. ``randomizer`` keys ``stall``,
    ``ack`` (latency >= 1) and ``status`` (0 ACK / 1 ERR / 2 RTY, weighted);
    ``status_hook(packet)`` overrides the status per request."""
    log = log or getattr(dut, '_log', None)
    if randomizer is None:
        randomizer = FlexRandomizer(WB4Slave._default_randomizer_constraints())
    return WB4Slave(dut, title, prefix, clock, registers=registers, addr_width=addr_width,
                    data_width=data_width, num_lines=num_lines, randomizer=randomizer,
                    max_outstanding=max_outstanding, status_hook=status_hook, log=log)


def create_wb4_monitor(dut, title, prefix, clock, addr_width=32, data_width=32, log=None):
    """A passive monitor: one packet per terminated transfer, plus the B4
    pipelined protocol checks in ``monitor.violations``."""
    log = log or getattr(dut, '_log', None)
    return WB4Monitor(dut, title, prefix, clock, addr_width=addr_width, data_width=data_width, log=log)
