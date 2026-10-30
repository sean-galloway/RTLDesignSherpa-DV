# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# Module: chi_factories
# Purpose: One-call creation of the CHI BFMs
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""Factory functions for the CHI BFMs.

    from CocoTBFramework.components.chi import (
        CHIConfig, create_chi_requester, create_chi_home, create_chi_monitor)

    rn_cfg = CHIConfig(node_type='RN-F', data_width=256)
    rn  = create_chi_requester(dut, "RN0", "s_chi_", dut.clk, rn_cfg, node_id=1, home_id=0,
                               reset=dut.rst_n)
    mon = create_chi_monitor(dut, "Mon", "s_chi_", dut.clk, rn_cfg, reset=dut.rst_n)
    txn = await rn.read(0x1000)
    assert mon.total_violations() == 0

``cfg`` may also be given as keyword properties (``data_width=512``) in
place of a :class:`CHIConfig`. Every factory validates the set.
"""

from .chi_config import CHIConfig, NodeType
from .chi_hn import CHIHome, CHIHomeNode, HomeOptions
from .chi_monitor import CHIMonitor
from .chi_rn import CHIRequestNode


def _cfg(cfg, props, node_type=None):
    if cfg is None:
        cfg = CHIConfig(**props)
    elif props:
        cfg = cfg.with_(**props)
    if node_type is not None and cfg.node_type != node_type:
        cfg = cfg.with_(node_type=node_type)
    return cfg.validate()


def create_chi_requester(dut, title, prefix, clock, cfg=None, node_id=0, home_id=0, cache=None, seed=0,
                         reset=None, signal_map=None, log=None, randomizer=None,
                         auto_link=True, idle_deactivate=None, rx_buffer_depth=None, pend_mode='exact', bus_name='',
                         **props):
    """An RN-F BFM driving a Home-side DUT (or the ``chi_wires`` loopback)."""
    return CHIRequestNode(dut, title, prefix, clock, _cfg(cfg, props), node_id=node_id, home_id=home_id,
                          cache=cache, seed=seed, reset=reset, signal_map=signal_map, log=log,
                          randomizer=randomizer, auto_link=auto_link,
                          idle_deactivate=idle_deactivate, rx_buffer_depth=rx_buffer_depth, pend_mode=pend_mode,
                          bus_name=bus_name)


def create_chi_home(dut, title, prefix, clock, cfg=None, home=None, rn_id=0, options=None, memory=None,
                    num_lines=1024, node_id=0, seed=0, reset=None, signal_map=None, log=None,
                    randomizer=None, auto_link=True, idle_deactivate=None,
                    rx_buffer_depth=None, pend_mode='exact', bus_name='', **props):
    """An HN-F port BFM serving an RN-side DUT. Pass the same ``home`` to
    several ports to share one memory and snoop filter."""
    c = _cfg(cfg, props, NodeType.HN_F if cfg is None and 'node_type' not in props else None)
    if home is None:
        home = CHIHome(c, memory=memory, num_lines=num_lines, options=options or HomeOptions(),
                       node_id=node_id, seed=seed, log=log or getattr(dut, '_log', None))
    return CHIHomeNode(dut, title, prefix, clock, c, home=home, rn_id=rn_id, reset=reset,
                       signal_map=signal_map, log=log, randomizer=randomizer,
                       auto_link=auto_link, idle_deactivate=idle_deactivate, rx_buffer_depth=rx_buffer_depth,
                       pend_mode=pend_mode, bus_name=bus_name)


def create_chi_monitor(dut, title, prefix, clock, cfg=None, reset=None, signal_map=None, log=None,
                       track_transactions=True, bus_name='', deactivate_credit_grace=1, **props):
    """A passive monitor + protocol checker on one CHI port. It plays the
    same node as the BFM beside it (both see the DUT port from across the
    link). ``deactivate_credit_grace``: cycles after LINKACTIVEREQ falls in
    which a grant is still legal (a DUT's synchronizer depth + 1)."""
    return CHIMonitor(dut, title, prefix, clock, _cfg(cfg, props), reset=reset, signal_map=signal_map,
                      log=log, track_transactions=track_transactions,
                      bus_name=bus_name, deactivate_credit_grace=deactivate_credit_grace)


__all__ = ['create_chi_requester', 'create_chi_home', 'create_chi_monitor']
