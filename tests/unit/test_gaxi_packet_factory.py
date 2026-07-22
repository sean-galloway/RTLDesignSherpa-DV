# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
"""Unit tests for the GAXI/FIFO packet-construction hook (``_build_packet``).

No simulator required: components are exercised through ``object.__new__``
shells (the pattern used by tests/unit/test_axi_compliance.py) so no cocotb
Bus/DUT wiring or coroutines are created. Factory wiring is verified by
monkeypatching the component classes in the factory module with recorders.

The hook exists so protocol BFMs that delegate to the GAXI pipelines keep
their own packet subclass: before it, the receive pipeline hard-coded
``GAXIPacket(self.field_config)``, so ``isinstance(pkt, AXIS5Packet)``
silently became False for delegating slaves/monitors.
"""

from __future__ import annotations

import inspect

import pytest

from CocoTBFramework.components.fifo.fifo_component_base import FIFOComponentBase
from CocoTBFramework.components.fifo.fifo_monitor_base import FIFOMonitorBase
from CocoTBFramework.components.fifo.fifo_packet import FIFOPacket
from CocoTBFramework.components.gaxi import gaxi_factories
from CocoTBFramework.components.gaxi.gaxi_component_base import GAXIComponentBase
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.gaxi.gaxi_monitor import GAXIMonitor
from CocoTBFramework.components.gaxi.gaxi_monitor_base import GAXIMonitorBase
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave
from CocoTBFramework.components.shared.field_config import FieldConfig
from CocoTBFramework.components.shared.packet import Packet


def make_field_config() -> FieldConfig:
    return FieldConfig.create_data_only(32)


def make_shell(cls, packet_class=None):
    """Build a simulator-free component shell exposing only what the hook needs."""
    shell = object.__new__(cls)
    shell.field_config = make_field_config()
    shell.packet_class = packet_class
    return shell


class CustomPacket(GAXIPacket):
    """Protocol packet that needs no extra constructor args."""


class ParityPacket(GAXIPacket):
    """Protocol packet requiring an extra constructor kwarg (AXIS5-like)."""

    def __init__(self, field_config=None, parity_enabled=False, **kwargs):
        super().__init__(field_config, **kwargs)
        self.parity_enabled = parity_enabled


# ---------------------------------------------------------------------------
# Default behavior: unchanged from before the hook existed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [GAXIComponentBase, GAXIMonitorBase, GAXIMonitor,
                                 GAXISlave, GAXIMaster])
def test_default_hook_yields_gaxi_packet(cls):
    """Unset packet_class → GAXIPacket, exactly as before the hook."""
    packet = make_shell(cls)._build_packet()
    assert type(packet) is GAXIPacket
    assert packet.field_config is not None


def test_default_hook_applies_field_values():
    """create_packet()'s historical field-assignment contract is preserved."""
    packet = make_shell(GAXIMonitorBase)._build_packet(data=0xDEAD)
    assert packet.data == 0xDEAD


def test_default_hook_ignores_unknown_field_names():
    """Unknown names are silently ignored, matching the old create_packet()."""
    packet = make_shell(GAXIMonitorBase)._build_packet(not_a_field=1)
    assert not hasattr(packet, "not_a_field")


def test_fifo_chassis_defaults_to_fifo_packet():
    """FIFO components default to FIFOPacket, not GAXIPacket."""
    for cls in (FIFOComponentBase, FIFOMonitorBase):
        assert type(make_shell(cls)._build_packet()) is FIFOPacket


# ---------------------------------------------------------------------------
# packet_class= now actually reaches the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [GAXIMonitorBase, GAXIMonitor, GAXISlave, GAXIMaster])
def test_packet_class_attribute_drives_hook(cls):
    packet = make_shell(cls, packet_class=CustomPacket)._build_packet()
    assert type(packet) is CustomPacket


def test_packet_class_overrides_fifo_default():
    packet = make_shell(FIFOMonitorBase, packet_class=CustomPacket)._build_packet()
    assert type(packet) is CustomPacket


def test_constructor_validates_packet_class():
    """A non-Packet packet_class fails fast at construction, not mid-sim."""
    shell = object.__new__(GAXIComponentBase)
    with pytest.raises(TypeError, match="must be a subclass of Packet"):
        GAXIComponentBase.__init__(
            shell, dut=None, title="t", prefix="", clock=None,
            field_config=None, protocol_type="gaxi_master", log=None,
            packet_class=str,
        )


def test_packet_class_accepts_any_packet_subclass():
    """Validation accepts non-GAXI Packet subclasses (e.g. FIFOPacket)."""
    assert issubclass(FIFOPacket, Packet)
    packet = make_shell(GAXIMonitorBase, packet_class=FIFOPacket)._build_packet()
    assert type(packet) is FIFOPacket


# ---------------------------------------------------------------------------
# Subclass override — the documented extension point
# ---------------------------------------------------------------------------


def test_subclass_hook_override_wins_over_default():
    class ParitySlave(GAXISlave):
        def _build_packet(self, **field_values):
            return ParityPacket(self.field_config, parity_enabled=True,
                                **field_values)

    shell = make_shell(ParitySlave)
    packet = shell._build_packet()
    assert isinstance(packet, ParityPacket)
    assert packet.parity_enabled is True


def test_subclass_hook_override_wins_over_packet_class():
    """An explicit override takes precedence over packet_class."""
    class ForcedMonitor(GAXIMonitor):
        def _build_packet(self, **field_values):
            return ParityPacket(self.field_config, parity_enabled=True)

    shell = make_shell(ForcedMonitor, packet_class=CustomPacket)
    assert type(shell._build_packet()) is ParityPacket


def test_create_packet_delegates_to_hook():
    """create_packet() must route through the hook, not construct directly."""
    class RecordingMonitor(GAXIMonitorBase):
        def _build_packet(self, **field_values):
            self.hook_calls = getattr(self, "hook_calls", [])
            self.hook_calls.append(field_values)
            return CustomPacket(self.field_config)

    shell = make_shell(RecordingMonitor)
    packet = shell.create_packet(data=0x55)
    assert type(packet) is CustomPacket
    assert shell.hook_calls == [{"data": 0x55}]


def test_master_create_packet_delegates_to_hook():
    shell = make_shell(GAXIMaster, packet_class=CustomPacket)
    packet = shell.create_packet(data=0x11)
    assert type(packet) is CustomPacket
    assert packet.data == 0x11


# ---------------------------------------------------------------------------
# Receive path — the site that motivated the hook
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [GAXIMonitor, GAXISlave])
def test_receive_path_constructs_via_hook(cls):
    """The receive coroutines must build packets via the hook.

    Guards the original bug: a hard-coded ``GAXIPacket(self.field_config)``
    in the receive path silently discards a delegating BFM's packet subclass.
    """
    source = inspect.getsource(cls)
    assert "self._build_packet()" in source
    assert "GAXIPacket(self.field_config)" not in source


def test_finish_packet_preserves_subclass_through_recvq(monkeypatch):
    """A hook-built subclass survives _finish_packet into _recvQ intact."""
    from collections import deque

    from CocoTBFramework.components.gaxi import gaxi_monitor_base

    # _finish_packet logs the sim time; there is no simulator under pytest.
    monkeypatch.setattr(gaxi_monitor_base, "get_sim_time", lambda units: 0)

    class Stats:
        received_transactions = 0
        transactions_observed = 0

    class Log:
        def debug(self, *args, **kwargs):
            pass

    shell = make_shell(GAXIMonitorBase, packet_class=CustomPacket)
    shell.stats = Stats()
    shell.log = Log()
    shell.title = "t"
    shell._recvQ = deque()
    shell._callbacks = []
    shell._event = None
    shell._wait_event = None
    shell._completed_packet_tracking = False
    shell._completedQ = deque()
    shell.data_collector = None

    packet = shell._build_packet()
    shell._finish_packet(123, packet, {"data": 0xABC})

    assert len(shell._recvQ) == 1
    received = shell._recvQ.popleft()
    assert type(received) is CustomPacket
    assert received.data == 0xABC
    assert received.end_time == 123


# ---------------------------------------------------------------------------
# Factory wiring: packet_class was accepted and dropped before this change
# ---------------------------------------------------------------------------


class Recorder:
    """Stand-in component capturing the kwargs a factory passes."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.mark.parametrize("factory_name,patched", [
    ("create_gaxi_master", "GAXIMaster"),
    ("create_gaxi_slave", "GAXISlave"),
    ("create_gaxi_monitor", "GAXIMonitor"),
])
def test_factory_forwards_packet_class(monkeypatch, factory_name, patched):
    monkeypatch.setattr(gaxi_factories, patched, Recorder)
    component = getattr(gaxi_factories, factory_name)(
        dut=None, title="t", prefix="", clock=None, packet_class=CustomPacket,
    )
    assert component.kwargs["packet_class"] is CustomPacket


@pytest.mark.parametrize("factory_name,patched", [
    ("create_gaxi_master", "GAXIMaster"),
    ("create_gaxi_slave", "GAXISlave"),
    ("create_gaxi_monitor", "GAXIMonitor"),
])
def test_factory_defaults_packet_class_to_none(monkeypatch, factory_name, patched):
    """Backward compatibility: unset → None → GAXIPacket downstream."""
    monkeypatch.setattr(gaxi_factories, patched, Recorder)
    component = getattr(gaxi_factories, factory_name)(
        dut=None, title="t", prefix="", clock=None,
    )
    assert component.kwargs["packet_class"] is None


def test_create_gaxi_components_forwards_packet_class(monkeypatch):
    """All four created components receive the packet_class."""
    for name in ("GAXIMaster", "GAXISlave", "GAXIMonitor"):
        monkeypatch.setattr(gaxi_factories, name, Recorder)
    monkeypatch.setattr(gaxi_factories, "GAXIScoreboard",
                        lambda *args, **kwargs: object())

    components = gaxi_factories.create_gaxi_components(
        dut=None, clock=None, packet_class=CustomPacket,
    )

    for key in ("master", "slave", "master_monitor", "slave_monitor"):
        assert components[key].kwargs["packet_class"] is CustomPacket


def test_create_gaxi_monitor_accepts_signal_map(monkeypatch):
    """Regression: create_gaxi_monitor referenced an undeclared signal_map."""
    monkeypatch.setattr(gaxi_factories, "GAXIMonitor", Recorder)
    component = gaxi_factories.create_gaxi_monitor(
        dut=None, title="t", prefix="", clock=None,
        signal_map={"valid": "v"},
    )
    assert component.kwargs["signal_map"] == {"valid": "v"}
