# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Same-ID responses go to the oldest waiting call (RDS-DV #94).

Two concurrent calls on one ID used to poll one per-ID deque, and whichever
woke first took the beats. These tests make the LATER call wait first (its
send returns sooner) and check it still gets the later response.
"""

import asyncio
import collections
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import CocoTBFramework.components.shared.id_order as id_order
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4MasterRead
from CocoTBFramework.components.axi5.axi5_interfaces import AXI5MasterRead


class Clock:
    """A tick counter; awaiting FakeEdge advances it by one."""

    def __init__(self):
        self.tick = 0


def fake_edge_for(clock):
    class FakeRisingEdge:
        def __init__(self, _clk):
            pass

        def __await__(self):
            clock.tick += 1
            yield from asyncio.sleep(0).__await__()
    return FakeRisingEdge


class FakeAR:
    """create_packet / send. Like GAXIMaster.send, a request is queued for
    the wire synchronously (wire order == call order). The FIRST send then
    returns only when `gate` is set; being woken by that event puts the first
    call behind the second in the scheduler's order, so the second call
    checks for responses first every cycle after -- the order that used to
    hand it the first call's response."""

    def __init__(self, clock):
        self.clock = clock
        self.sent = []
        self.gate = asyncio.Event()

    def create_packet(self, **kw):
        return SimpleNamespace(**kw)

    async def send(self, pkt):
        self.sent.append(pkt.addr)
        if len(self.sent) == 1:
            await self.gate.wait()


def make_master(cls, clock):
    m = object.__new__(cls)
    m.clock = clock
    m.data_width = 32
    m.timeout_cycles = 200
    m.log = None
    m.ar_channel = FakeAR(clock)
    m._response_by_id = collections.defaultdict(collections.deque)
    m._waiters_by_id = id_order.new_waiters()
    return m


async def drive(master, clock, beats_at):
    """Release the first send at tick 5, then deliver R beats through the
    master's own callback at the given ticks."""
    pending = sorted(beats_at, key=lambda b: b[0])
    while pending:
        await asyncio.sleep(0)
        if clock.tick >= 5:
            master.ar_channel.gate.set()
        while pending and clock.tick >= pending[0][0]:
            _, pkt = pending.pop(0)
            master._on_r_response(pkt)


@pytest.mark.parametrize("cls", [AXI4MasterRead, AXI5MasterRead])
def test_same_id_reads_get_their_own_data(cls):
    clock = Clock()
    m = make_master(cls, clock)
    beat = lambda d: SimpleNamespace(id=3, data=d, resp=0, last=1)

    async def run():
        with patch.object(id_order, "RisingEdge", fake_edge_for(clock)), \
             patch(f"{cls.__module__}.RisingEdge", fake_edge_for(clock)):
            first = asyncio.ensure_future(m.read_transaction(0x100, burst_len=1, id=3))
            second = asyncio.ensure_future(m.read_transaction(0x200, burst_len=1, id=3))
            feeder = asyncio.ensure_future(drive(m, clock, [(20, beat(0xA)), (40, beat(0xB))]))
            r1, r2 = await asyncio.gather(first, second)
            await feeder
            return r1, r2

    r1, r2 = asyncio.run(run())
    assert m.ar_channel.sent == [0x100, 0x200], "requests left in call order"
    data = lambda r: r[0]['data'] if isinstance(r[0], dict) else r[0]
    assert data(r1) == 0xA and data(r2) == 0xB, (
        f"first call got {data(r1):#x}, second {data(r2):#x}: same-ID responses swapped")
    assert not m._waiters_by_id, "every ticket released"


def test_timeout_releases_the_line():
    """A call that times out leaves the line; the call behind it is served."""
    clock = Clock()
    waiters = id_order.new_waiters()
    responses = collections.defaultdict(collections.deque)

    async def run():
        with patch.object(id_order, "RisingEdge", fake_edge_for(clock)):
            t1 = id_order.take_ticket(waiters, 7)
            t2 = id_order.take_ticket(waiters, 7)
            stuck = asyncio.ensure_future(id_order.wait_turn(
                clock, waiters, responses, 7, t1, 2, 10, lambda c, r: f"timeout {c} {r}"))
            behind = asyncio.ensure_future(id_order.wait_turn(
                clock, waiters, responses, 7, t2, 1, 100, lambda c, r: f"timeout {c} {r}"))
            responses[7].append("only-one-beat")
            with pytest.raises(TimeoutError):
                await stuck
            return await behind

    assert asyncio.run(run()) == ["only-one-beat"]
    assert not waiters
