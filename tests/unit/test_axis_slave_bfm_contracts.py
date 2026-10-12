# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""AXIS / AXIS5 BFM contracts that broke silently (RTLDesignSherpa-DV#89).

Covers, without a simulator:

- The AXIS5 packet's pin-less ``parity_error`` status field binds to no pin,
  so the AXIS5 master/slave/monitor must declare it optional themselves; a
  multi-signal AXIS5 BFM used to fail construction unless every caller passed
  ``optional_fields=('parity_error',)``.
- ``AXISSlave.apply_backpressure`` called ``FlexRandomizer.update_constraints``,
  which does not exist, so every call raised AttributeError.
- The AXIS slave registered its own frame tracker through ``add_callback``.
  cocotb's ``Monitor._recv`` stops filling ``_recvQ`` once any callback exists,
  so ``slave._recvQ`` stayed empty forever.
"""

from __future__ import annotations

import logging
from collections import deque

import pytest

from CocoTBFramework.components.axis4.axis_master import AXISMaster
from CocoTBFramework.components.axis4.axis_monitor import AXISMonitor
from CocoTBFramework.components.axis4.axis_packet import AXISPacket
from CocoTBFramework.components.axis4.axis_slave import AXISSlave
from CocoTBFramework.components.axis4.axis_field_configs import AXISFieldConfigs
from CocoTBFramework.components.axis5.axis5_master import AXIS5Master
from CocoTBFramework.components.axis5.axis5_monitor import AXIS5Monitor
from CocoTBFramework.components.axis5.axis5_slave import AXIS5Slave
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer


# ----------------------------------------------------------------------
# (a) parity_error is declared optional by the AXIS5 BFMs themselves
# ----------------------------------------------------------------------

class _Stop(Exception):
    """Raised by the patched parent __init__ once kwargs are captured."""


AXIS5_PARENTS = [
    (AXIS5Master, AXISMaster),
    (AXIS5Slave, AXISSlave),
    (AXIS5Monitor, AXISMonitor),
]


def _captured_parent_kwargs(monkeypatch, cls, parent, **ctor_kwargs):
    captured = {}

    def fake_init(self, *args, **kwargs):
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr(parent, "__init__", fake_init)
    with pytest.raises(_Stop):
        cls(dut=None, title="unit", prefix="m_axis_", clock=None,
            multi_sig=True, enable_wakeup=True, enable_parity=True,
            **ctor_kwargs)
    return captured


@pytest.mark.parametrize("cls,parent", AXIS5_PARENTS)
def test_axis5_bfm_declares_parity_error_optional(monkeypatch, cls, parent):
    kwargs = _captured_parent_kwargs(monkeypatch, cls, parent)
    assert "parity_error" in set(kwargs.get("optional_fields") or ())


@pytest.mark.parametrize("cls,parent", AXIS5_PARENTS)
def test_axis5_bfm_keeps_caller_optional_fields(monkeypatch, cls, parent):
    kwargs = _captured_parent_kwargs(monkeypatch, cls, parent,
                                     optional_fields=("user",))
    assert {"parity_error", "user"} <= set(kwargs["optional_fields"])


@pytest.mark.parametrize("cls,parent", AXIS5_PARENTS)
def test_axis5_bfm_declares_nothing_without_parity(monkeypatch, cls, parent):
    """No parity -> no parity_error field -> nothing to opt out."""
    captured = {}

    def fake_init(self, *args, **kwargs):
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr(parent, "__init__", fake_init)
    with pytest.raises(_Stop):
        cls(dut=None, title="unit", prefix="m_axis_", clock=None,
            multi_sig=True, enable_parity=False)
    assert "parity_error" not in set(captured.get("optional_fields") or ())


# ----------------------------------------------------------------------
# AXISSlave built through its real __init__ on a stubbed GAXI chassis
# ----------------------------------------------------------------------

class _Stats:
    received_transactions = 0


def _stub_gaxi_slave_init(self, **kwargs):
    """Stand-in for GAXISlave.__init__: just the state the AXIS layer and
    cocotb's Monitor._recv/add_callback touch."""
    self.title = kwargs["title"]
    self.log = logging.getLogger("unit.axis_slave")
    self.mode = kwargs.get("mode", "skid")
    self.timeout_cycles = kwargs.get("timeout_cycles", 1000)
    self.super_debug = False
    self.field_config = kwargs["field_config"]
    self.randomizer = kwargs.get("randomizer")
    self.packet_class = None
    self.callbacks = []
    self._callbacks = []
    self._recvQ = deque()
    self._event = None
    self._wait_event = None
    self.stats = _Stats()


@pytest.fixture
def axis_slave(monkeypatch):
    monkeypatch.setattr(GAXISlave, "__init__", _stub_gaxi_slave_init)
    return AXISSlave(
        dut=None, title="unit", prefix="m_axis_", clock=None,
        randomizer=FlexRandomizer({"ready_delay": ([(0, 0)], [1])}),
    )


def _beat(slave, data=0x11223344, last=1):
    cfg = slave.field_config
    pkt = AXISPacket(cfg)
    pkt.data = data
    pkt.strb = (1 << cfg["strb"].bits) - 1
    pkt.last = last
    return pkt


# ----------------------------------------------------------------------
# (b) apply_backpressure uses the real FlexRandomizer API
# ----------------------------------------------------------------------

def test_apply_backpressure_always_stalls_at_probability_one(axis_slave):
    old = axis_slave.randomizer
    axis_slave.apply_backpressure(probability=1.0, min_cycles=3, max_cycles=3)
    assert {axis_slave.randomizer.next()["ready_delay"] for _ in range(50)} == {3}
    # The previous randomizer is replaced, not mutated
    assert old.next()["ready_delay"] == 0


def test_apply_backpressure_never_stalls_at_probability_zero(axis_slave):
    axis_slave.apply_backpressure(probability=0.0, min_cycles=2, max_cycles=9)
    assert {axis_slave.randomizer.next()["ready_delay"] for _ in range(50)} == {0}


def test_apply_backpressure_mixes_within_bounds(axis_slave):
    axis_slave.apply_backpressure(probability=0.5, min_cycles=2, max_cycles=4)
    seen = {axis_slave.randomizer.next()["ready_delay"] for _ in range(400)}
    assert 0 in seen
    assert seen <= {0, 2, 3, 4}
    assert seen & {2, 3, 4}


@pytest.mark.parametrize("probability,lo,hi", [
    (-0.1, 1, 5), (1.5, 1, 5), (0.5, 0, 5), (0.5, 6, 5),
])
def test_apply_backpressure_rejects_bad_arguments(axis_slave, probability, lo, hi):
    with pytest.raises(ValueError):
        axis_slave.apply_backpressure(probability=probability,
                                      min_cycles=lo, max_cycles=hi)


# ----------------------------------------------------------------------
# (c) _recvQ is filled; the internal frame tracker is not a callback
# ----------------------------------------------------------------------

def test_slave_registers_no_callback_of_its_own(axis_slave):
    assert axis_slave._callbacks == []


def test_received_packet_reaches_recvq_and_frame_tracking(axis_slave):
    pkt = _beat(axis_slave)
    axis_slave._recv(pkt)
    assert list(axis_slave._recvQ) == [pkt]
    assert axis_slave.packets_received == 1
    assert axis_slave.frames_received == 1


def test_user_callback_follows_cocotb_contract(axis_slave):
    """A user callback gets every packet and, as for any cocotb Monitor,
    replaces the _recvQ; frame tracking keeps counting either way."""
    got = []
    axis_slave.add_callback(got.append)
    pkt = _beat(axis_slave)
    axis_slave._recv(pkt)
    assert got == [pkt]
    assert list(axis_slave._recvQ) == []
    assert axis_slave.packets_received == 1


def test_axis5_slave_flags_parity_before_delivery(monkeypatch):
    """The AXIS5 parity check runs before consumers see the packet."""
    monkeypatch.setattr(GAXISlave, "__init__", _stub_gaxi_slave_init)
    monkeypatch.setattr(AXIS5Slave, "_resolve_axis5_signals",
                        lambda self: setattr(self, "wakeup_signal", None))
    slave = AXIS5Slave(dut=None, title="unit", prefix="m_axis_", clock=None,
                       enable_parity=True)
    seen = []
    slave.add_callback(lambda p: seen.append(p.parity_error))
    bad = slave._build_packet()
    bad.data = 0xCAFEBABE
    bad.strb = (1 << slave.field_config["strb"].bits) - 1
    bad.last = 1
    bad.fill_check_fields()
    bad.datachk ^= 0b1
    slave._recv(bad)
    assert seen == [1]
    assert slave.parity_errors_detected == 1
