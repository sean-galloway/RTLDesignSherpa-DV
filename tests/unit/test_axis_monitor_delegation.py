"""Unit tests for AXIS4/AXIS5 monitor delegation to the GAXI pipeline.

Owner decree: GAXI is the underlying workhorse of all the other AXI*
interfaces, so AXIS components must not fork its receive logic.

Covers, without a simulator:
- AXISMonitor/AXIS5Monitor inherit GAXIMonitor's receive loop and no longer
  define their own ``_monitor_recv``
- The ``_build_packet`` hook yields real AXISPacket/AXIS5Packet instances
  (and still honours an explicit ``packet_class=``)
- ``_finish_packet`` runs the GAXI completion first, then the AXIS hook
- TLAST frame tracking, AXIS protocol violation checks, and AXIS5 parity
  checking all work on synthetic packets fed through the delegated hook
- AXIS4 and AXIS5 stay structurally symmetric (monitor vs slave)
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.axis4.axis_field_configs import AXISFieldConfigs
from CocoTBFramework.components.axis4.axis_monitor import AXISMonitor
from CocoTBFramework.components.axis4.axis_packet import AXISPacket
from CocoTBFramework.components.axis4.axis_slave import AXISSlave
from CocoTBFramework.components.axis5.axis5_field_configs import AXIS5FieldConfigs
from CocoTBFramework.components.axis5.axis5_monitor import AXIS5Monitor
from CocoTBFramework.components.axis5.axis5_packet import AXIS5Packet
from CocoTBFramework.components.axis5.axis5_slave import AXIS5Slave
from CocoTBFramework.components.gaxi.gaxi_monitor import GAXIMonitor
from CocoTBFramework.components.gaxi.gaxi_monitor_base import GAXIMonitorBase
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave

# ----------------------------------------------------------------------
# Simulator-free component stand-ins
#
# The AXIS monitors/slaves cannot be constructed without a cocotb DUT, so
# these helpers build bare instances and populate only the attributes the
# hooks under test touch. Nothing here bypasses the production hook code:
# the real _build_packet / _finish_packet / _axis_packet_observed methods
# are invoked.
# ----------------------------------------------------------------------


def _axis_config(data_width: int = 32):
    return AXISFieldConfigs.create_default_axis_config(data_width=data_width)


def _axis5_config(data_width: int = 32, enable_parity: bool = True):
    return AXIS5FieldConfigs.create_axis5_field_config(
        data_width=data_width, enable_wakeup=True, enable_parity=enable_parity
    )


def _bare(cls, field_config, **attrs):
    """Build an un-initialized component with the hook state populated."""
    obj = object.__new__(cls)
    obj.field_config = field_config
    obj.packet_class = None
    obj.log = None
    obj.super_debug = False
    obj.memory_model = None
    obj.title = "unit"
    # AXIS frame/statistics state (mirrors __init__)
    obj._current_frame = []
    obj._frame_id = None
    obj.packets_observed = 0
    obj.frames_observed = 0
    obj.total_data_bytes = 0
    obj.protocol_violations = 0
    for name, value in attrs.items():
        setattr(obj, name, value)
    return obj


def _bare_axis_monitor(data_width: int = 32):
    return _bare(AXISMonitor, _axis_config(data_width), is_slave=False)


def _bare_axis5_monitor(data_width: int = 32, enable_parity: bool = True):
    return _bare(
        AXIS5Monitor,
        _axis5_config(data_width, enable_parity),
        is_slave=False,
        enable_wakeup=True,
        enable_parity=enable_parity,
        axis5_protocol_violations=0,
        parity_errors_observed=0,
        parity_checks_passed=0,
        wakeup_events=0,
        wakeup_violations=0,
        _wakeup_active=False,
        _wakeup_history=[],
    )


def _bare_axis5_slave(data_width: int = 32, enable_parity: bool = True):
    return _bare(
        AXIS5Slave,
        _axis5_config(data_width, enable_parity),
        enable_wakeup=True,
        enable_parity=enable_parity,
        parity_errors_detected=0,
        parity_checks_passed=0,
    )


def _beat(field_config, data, last=0, id=0, strb=None):
    pkt = AXISPacket(field_config)
    pkt.data = data
    pkt.strb = (1 << field_config["strb"].bits) - 1 if strb is None else strb
    pkt.last = last
    pkt.id = id
    return pkt


# ----------------------------------------------------------------------
# The monitors must delegate, not fork, the receive loop
# ----------------------------------------------------------------------


def test_axis_monitors_inherit_the_gaxi_receive_pipeline():
    assert issubclass(AXISMonitor, GAXIMonitor)
    assert issubclass(AXIS5Monitor, AXISMonitor)


@pytest.mark.parametrize("cls", [AXISMonitor, AXIS5Monitor])
def test_axis_monitors_do_not_define_their_own_monitor_recv(cls):
    """Guard: the forked _monitor_recv loops must stay deleted."""
    assert "_monitor_recv" not in cls.__dict__
    assert cls._monitor_recv is GAXIMonitor._monitor_recv


@pytest.mark.parametrize("cls", [AXISSlave, AXIS5Slave])
def test_axis_slaves_do_not_define_their_own_monitor_recv(cls):
    assert "_monitor_recv" not in cls.__dict__
    assert cls._monitor_recv is GAXISlave._monitor_recv


def test_axis_monitor_finish_packet_runs_gaxi_completion_first(monkeypatch):
    """_finish_packet must delegate to GAXI, then layer AXIS accounting."""
    order = []

    def fake_finish(self, current_time, packet, data_dict=None):
        order.append("gaxi")

    monkeypatch.setattr(GAXIMonitorBase, "_finish_packet", fake_finish)

    mon = _bare_axis_monitor()
    original_hook = AXISMonitor._axis_packet_observed

    def spy_hook(self, packet):
        order.append("axis")
        original_hook(self, packet)

    monkeypatch.setattr(AXISMonitor, "_axis_packet_observed", spy_hook)

    mon._finish_packet(0, _beat(mon.field_config, 0x1234, last=1))

    assert order == ["gaxi", "axis"]
    assert mon.packets_observed == 1


# ----------------------------------------------------------------------
# _build_packet hook: real AXIS packet classes again
# ----------------------------------------------------------------------


def test_axis_monitor_builds_axis_packets():
    mon = _bare_axis_monitor()
    assert AXISMonitor._default_packet_class is AXISPacket

    pkt = mon._build_packet()
    assert isinstance(pkt, AXISPacket)
    assert pkt.field_config is mon.field_config


def test_axis_monitor_build_packet_applies_field_values():
    mon = _bare_axis_monitor()
    pkt = mon._build_packet(data=0xDEADBEEF, last=1)
    assert pkt.data == 0xDEADBEEF
    assert pkt.last == 1


def test_axis_monitor_build_packet_honours_explicit_packet_class():
    class MyAXISPacket(AXISPacket):
        pass

    mon = _bare_axis_monitor()
    mon.packet_class = MyAXISPacket
    assert isinstance(mon._build_packet(), MyAXISPacket)


def test_axis5_monitor_builds_axis5_packets_with_options():
    mon = _bare_axis5_monitor(data_width=64, enable_parity=True)
    assert AXIS5Monitor._default_packet_class is AXIS5Packet

    pkt = mon._build_packet()
    assert isinstance(pkt, AXIS5Packet)
    assert pkt.enable_parity is True
    assert pkt.enable_wakeup is True
    # data_width comes from the field config, so parity self-check is correct
    assert pkt.data_width == 64
    assert pkt.parity_width == 8


def test_axis5_slave_builds_axis5_packets_with_options():
    slave = _bare_axis5_slave(data_width=32, enable_parity=True)
    assert AXIS5Slave._default_packet_class is AXIS5Packet

    pkt = slave._build_packet()
    assert isinstance(pkt, AXIS5Packet)
    assert pkt.enable_parity is True
    assert pkt.parity_width == 4


def test_axis_slave_default_packet_class_is_axis_packet():
    assert AXISSlave._default_packet_class is AXISPacket
    assert issubclass(AXISPacket, GAXIPacket)


# ----------------------------------------------------------------------
# TLAST frame tracking through the delegated hook
# ----------------------------------------------------------------------


def test_frame_tracking_counts_beats_and_frames():
    mon = _bare_axis_monitor()
    cfg = mon.field_config

    mon._axis_packet_observed(_beat(cfg, 0x11111111, last=0, id=7))
    mon._axis_packet_observed(_beat(cfg, 0x22222222, last=0, id=7))

    # Mid-frame: frame open, id latched from the first beat
    assert mon.packets_observed == 2
    assert mon.frames_observed == 0
    assert mon._frame_id == 7
    info = mon.get_current_frame_info()
    assert info["packets_in_frame"] == 2
    assert info["frame_id"] == 7
    assert info["is_receiving"] is True
    assert info["total_bytes"] == 8  # two full-strobe 32-bit beats

    mon._axis_packet_observed(_beat(cfg, 0x33333333, last=1, id=7))

    # TLAST closes the frame and resets the per-frame state
    assert mon.packets_observed == 3
    assert mon.frames_observed == 1
    assert mon.total_data_bytes == 12
    assert mon._current_frame == []
    assert mon._frame_id is None
    assert mon.get_current_frame_info()["is_receiving"] is False


def test_frame_tracking_partial_strobe_byte_count():
    mon = _bare_axis_monitor()
    cfg = mon.field_config
    # 0b0011 -> 2 valid bytes
    mon._axis_packet_observed(_beat(cfg, 0x0000BEEF, last=1, strb=0b0011))
    assert mon.total_data_bytes == 2
    assert mon.frames_observed == 1


def test_single_beat_frame_never_latches_a_frame_id():
    mon = _bare_axis_monitor()
    mon._axis_packet_observed(_beat(mon.field_config, 0xA5, last=1, id=3))
    assert mon.frames_observed == 1
    assert mon._frame_id is None


# ----------------------------------------------------------------------
# AXIS protocol violation checks still run on observed packets
# ----------------------------------------------------------------------


def test_non_contiguous_strobe_is_flagged():
    mon = _bare_axis_monitor()
    # 0b1011 has a hole at bit 2
    mon._axis_packet_observed(_beat(mon.field_config, 0x11223344, last=1, strb=0b1011))
    assert mon.protocol_violations == 1


def test_zero_strobe_with_data_is_flagged():
    mon = _bare_axis_monitor()
    mon._axis_packet_observed(_beat(mon.field_config, 0x11223344, last=1, strb=0))
    assert mon.protocol_violations == 1


def test_clean_beat_is_not_flagged():
    mon = _bare_axis_monitor()
    mon._axis_packet_observed(_beat(mon.field_config, 0x11223344, last=1))
    assert mon.protocol_violations == 0


# ----------------------------------------------------------------------
# AXIS5 parity checking through the delegated hook
# ----------------------------------------------------------------------


def _axis5_beat(mon, data, last=1, corrupt_parity=False):
    pkt = mon._build_packet()
    pkt.data = data
    pkt.strb = (1 << mon.field_config["strb"].bits) - 1
    pkt.last = last
    pkt.parity = pkt.calculate_parity() ^ (0b1 if corrupt_parity else 0)
    return pkt


def test_axis5_monitor_accepts_good_parity():
    mon = _bare_axis5_monitor()
    mon._axis_packet_observed(_axis5_beat(mon, 0x12345678))

    assert mon.parity_checks_passed == 1
    assert mon.parity_errors_observed == 0
    # AXIS frame tracking still ran through the AXIS4 base hook
    assert mon.packets_observed == 1
    assert mon.frames_observed == 1


def test_axis5_monitor_detects_corrupted_parity():
    mon = _bare_axis5_monitor()
    pkt = _axis5_beat(mon, 0x12345678, corrupt_parity=True)
    mon._axis_packet_observed(pkt)

    assert mon.parity_errors_observed == 1
    assert mon.parity_checks_passed == 0
    assert pkt.parity_error == 1
    assert mon.get_parity_stats()["error_rate"] == 1.0


def test_axis5_monitor_skips_parity_when_disabled():
    mon = _bare_axis5_monitor(enable_parity=False)
    pkt = mon._build_packet()
    pkt.data = 0x12345678
    pkt.strb = (1 << mon.field_config["strb"].bits) - 1
    pkt.last = 1
    mon._axis_packet_observed(pkt)

    assert mon.parity_checks_passed == 0
    assert mon.parity_errors_observed == 0
    assert mon.packets_observed == 1


def test_axis5_slave_parity_check_good_and_corrupted():
    slave = _bare_axis5_slave()

    good = slave._build_packet()
    good.data = 0xCAFEBABE
    good.parity = good.calculate_parity()
    slave._check_parity(good)
    assert slave.parity_checks_passed == 1
    assert slave.parity_errors_detected == 0

    bad = slave._build_packet()
    bad.data = 0xCAFEBABE
    bad.parity = bad.calculate_parity() ^ 0b1
    slave._check_parity(bad)
    assert slave.parity_errors_detected == 1
    assert bad.parity_error == 1


# ----------------------------------------------------------------------
# AXIS4 vs AXIS5 symmetry (the audit found repeated drift)
# ----------------------------------------------------------------------


def test_axis4_and_axis5_use_the_same_extension_points():
    # Both monitors layer AXIS behaviour on the same hook name...
    assert "_axis_packet_observed" in AXISMonitor.__dict__
    assert "_axis_packet_observed" in AXIS5Monitor.__dict__
    # ...and only AXIS4 owns the _finish_packet bridge into it.
    assert "_finish_packet" in AXISMonitor.__dict__
    assert "_finish_packet" not in AXIS5Monitor.__dict__

    # Both slaves layer AXIS behaviour on the slave-side callback hook.
    assert "_axis_packet_callback" in AXISSlave.__dict__
    assert "_axis_packet_callback" in AXIS5Slave.__dict__

    # AXIS5 monitor and slave build packets identically.
    assert "_build_packet" in AXIS5Monitor.__dict__
    assert "_build_packet" in AXIS5Slave.__dict__


def test_axis5_data_width_helpers_agree():
    mon = _bare_axis5_monitor(data_width=64)
    slave = _bare_axis5_slave(data_width=64)
    assert mon._axis5_data_width() == slave._axis5_data_width() == 64
