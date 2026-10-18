# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""set_ready_policy('always') must not raise READY out of band.

The receive loop, parked in its valid_first wait, wakes only on rising edges
and does not sample. Raising READY from outside let a beat handshake on the
pins in that window and never be recorded: one W beat of a write vanished and
the burst landed a beat short (RTLDesignSherpa axi3_loopback, 2026-10-18).
The loop now raises READY itself, after leaving the wait when the policy
changes.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import CocoTBFramework.components.gaxi.gaxi_slave as gaxi_slave_mod
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave


class Sig:
    def __init__(self, v):
        self.value = SimpleNamespace(is_resolvable=True, __int__=None)
        self.v = v

    @property
    def value(self):
        return _Val(self.v)

    @value.setter
    def value(self, v):
        if not isinstance(v, SimpleNamespace):
            self.v = int(v)


class _Val:
    def __init__(self, v):
        self.v = v
        self.is_resolvable = True

    def __int__(self):
        return self.v


def make_slave(policy):
    g = object.__new__(GAXISlave)
    g.title = 'W_Slave'
    g.pipeline_debug = False
    g.ready_policy = policy
    g.ready_sig = Sig(0)
    g.valid_sig = Sig(0)
    g.log = SimpleNamespace(debug=lambda *a, **k: None)
    return g


def test_always_does_not_drive_ready():
    g = make_slave('valid_first')
    g.set_ready_policy('always')
    assert g.ready_policy == 'always'
    assert int(g.ready_sig.value) == 0, "set_ready_policy('always') raised READY out of band"


def test_stall_still_drops_ready_at_once():
    g = make_slave('always')
    g.ready_sig.v = 1
    g.set_ready_policy('stall')
    assert int(g.ready_sig.value) == 0


def test_valid_first_wait_leaves_on_policy_change():
    """Parked in the valid_first wait with VALID low, a switch to 'always'
    ends the wait at the next edge; READY is raised by the loop, and the
    randomized delay is skipped."""
    g = make_slave('valid_first')
    g.phase_statistics = {'phase2_count': 0}
    calls = {'rand': 0, 'edges': 0}
    g.randomizer = SimpleNamespace(next=lambda: calls.__setitem__('rand', calls['rand'] + 1) or {'ready_delay': 3})

    async def wait_cycles(n):
        calls['edges'] += 1
        if calls['edges'] == 2:
            g.set_ready_policy('always')
        await asyncio.sleep(0)
    g.wait_cycles = wait_cycles

    class FakeEdge:
        def __init__(self, _clk):
            pass

        def __await__(self):
            yield from asyncio.sleep(0).__await__()

    g.clock = object()
    with patch.object(gaxi_slave_mod, 'FallingEdge', FakeEdge):
        asyncio.run(asyncio.wait_for(g._recv_phase2(), 1.0))
    assert calls['rand'] == 0, "applied the valid_first randomized delay after switching to 'always'"
    assert int(g.ready_sig.value) == 1
