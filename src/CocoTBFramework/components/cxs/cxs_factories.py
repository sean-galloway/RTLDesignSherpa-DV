# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# Module: cxs_factories
# Purpose: One-call creation of the CXS BFMs
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""Factory functions for the CXS BFMs.

    from CocoTBFramework.components.cxs import (
        CXSConfig, CXSIssue, create_cxs_transmitter, create_cxs_receiver,
        create_cxs_monitor)

    cfg = CXSConfig(issue=CXSIssue.B, data_width=512, max_pkt_per_flit=2,
                    has_last=True, has_prcltype=True)
    tx  = create_cxs_transmitter(dut, "TX", "s_cxs_", dut.aclk, cfg, reset=dut.aresetn)
    mon = create_cxs_monitor(dut, "Mon", "s_cxs_", dut.aclk, cfg, reset=dut.aresetn)

``cfg`` may also be given as keyword properties (``issue='C',
data_width=128, max_pkt_per_flit=1``) instead of a :class:`CXSConfig`.
Every factory validates the property set for its issue.
"""

from .cxs_components import CXSMonitor, CXSReceiver, CXSTransmitter
from .cxs_config import CXSConfig


def _cfg(cfg, props):
    if cfg is None:
        cfg = CXSConfig(**props)
    elif props:
        cfg = cfg.with_(**props)
    return cfg.validate()


def create_cxs_transmitter(dut, title, prefix, clock, cfg=None, randomizer=None,
                           auto_link=True, idle_deactivate=16, reset=None,
                           signal_map=None, log=None, bus_name='', **props):
    """Drive a CXS receiver DUT. ``randomizer`` key ``valid_gap``."""
    return CXSTransmitter(dut, title, prefix, clock, _cfg(cfg, props), randomizer=randomizer,
                          auto_link=auto_link, idle_deactivate=idle_deactivate, reset=reset,
                          signal_map=signal_map, log=log, bus_name=bus_name)


def create_cxs_receiver(dut, title, prefix, clock, cfg=None, buffer_depth=None,
                        randomizer=None, reset=None, signal_map=None, log=None,
                        packet_callback=None, bus_name='', **props):
    """Receive from a CXS transmitter DUT. ``randomizer`` keys ``grant_gap``,
    ``drain_gap``, ``ack_delay``."""
    return CXSReceiver(dut, title, prefix, clock, _cfg(cfg, props), buffer_depth=buffer_depth,
                       randomizer=randomizer, reset=reset, signal_map=signal_map, log=log,
                       packet_callback=packet_callback, bus_name=bus_name)


def create_cxs_monitor(dut, title, prefix, clock, cfg=None, reset=None, signal_map=None,
                       log=None, packet_callback=None, bus_name='', **props):
    """A passive monitor + protocol checker on one CXS link."""
    return CXSMonitor(dut, title, prefix, clock, _cfg(cfg, props), reset=reset,
                      signal_map=signal_map, log=log, packet_callback=packet_callback, bus_name=bus_name)
