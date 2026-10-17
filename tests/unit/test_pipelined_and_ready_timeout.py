# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Requester `pipelined` mode, and the channel driver's READY timeout.

`pipelined=True` queues the address straight onto the channel driver
(`_driver_send`) instead of `send()`, which waits for the transmit pipeline
to drain -- the drain left a dead cycle between back-to-back bursts.

The GAXI master's READY wait used to raise `cocotb.result.TestFailure`,
which cocotb 2.x removed: the timeout surfaced as an AttributeError and the
transmit pipeline logged "module 'cocotb' has no attribute 'result'" in
place of the timeout it was reporting.
"""

import asyncio
import collections
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import CocoTBFramework.components.gaxi.gaxi_master as gaxi_master_mod
import CocoTBFramework.components.shared.id_order as id_order
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4MasterRead
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster


class FakeEdge:
    def __init__(self, _clk):
        pass

    def __await__(self):
        yield from asyncio.sleep(0).__await__()


class FakeAR:
    def __init__(self):
        self.calls = []

    def create_packet(self, **kw):
        return SimpleNamespace(**kw)

    async def send(self, pkt):
        self.calls.append('send')

    async def _driver_send(self, pkt):
        self.calls.append('_driver_send')


def make_reader(pipelined):
    m = object.__new__(AXI4MasterRead)
    m.clock = object()
    m.data_width = 32
    m.timeout_cycles = 3
    m.log = None
    m.ar_channel = FakeAR()
    m._response_by_id = collections.defaultdict(collections.deque)
    m._waiters_by_id = id_order.new_waiters()
    if pipelined is not None:
        m.pipelined = pipelined
    return m


@pytest.mark.parametrize('pipelined, expect', [(True, '_driver_send'),
                                               (False, 'send'),
                                               (None, 'send')])
def test_pipelined_selects_the_driver_queue(pipelined, expect):
    m = make_reader(pipelined)
    with patch.object(id_order, 'RisingEdge', FakeEdge):
        try:
            asyncio.run(m.read_transaction(0x100, burst_len=1, id=0))
        except Exception:
            pass   # no R ever arrives; only the AR path is under test
    assert m.ar_channel.calls == [expect]


def test_ready_timeout_raises_timeout_error():
    g = object.__new__(GAXIMaster)
    g.pipeline_debug = False
    g.phase_statistics = collections.defaultdict(int)
    g.timeout_cycles = 4
    g.title = 'AW_Master'
    g.clock = object()
    g.ready_sig = SimpleNamespace(value=0)
    g.log = SimpleNamespace(error=lambda *a, **k: None, debug=lambda *a, **k: None)
    g.stats = SimpleNamespace(record_timeout=lambda: None)
    g._drive_signals = lambda txn: True
    g._assign_valid_value = lambda v: None
    g._clear_data_bus = lambda: None
    with patch.object(gaxi_master_mod, 'RisingEdge', FakeEdge):
        with pytest.raises(TimeoutError, match='No ready signal after 4 cycles'):
            asyncio.run(g._xmit_phase2(SimpleNamespace()))
