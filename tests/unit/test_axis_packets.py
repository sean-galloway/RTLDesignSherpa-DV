"""Unit tests for AXIS4/AXIS5 packets (pure Python, no simulator).

Covers the AXIS behavior that is testable without a DUT:
- AXIS5 TPARITY is odd parity per byte (AMBA AXI5-Stream), checked against
  hand-computed vectors
- AXIS5Packet.copy() preserves constructor options (enable_parity,
  enable_wakeup, data_width) so copies do not trivially pass check_parity
- AXISPacket strobe/byte helpers and the create_axis_packet factory
- axis_factories delegates to the AXIS classes (not raw GAXI classes)
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.axis4 import axis_factories
from CocoTBFramework.components.axis4.axis_field_configs import AXISFieldConfigs
from CocoTBFramework.components.axis4.axis_master import AXISMaster
from CocoTBFramework.components.axis4.axis_monitor import AXISMonitor
from CocoTBFramework.components.axis4.axis_packet import AXISPacket, create_axis_packet
from CocoTBFramework.components.axis4.axis_slave import AXISSlave
from CocoTBFramework.components.axis5.axis5_monitor import AXIS5Monitor
from CocoTBFramework.components.axis5.axis5_packet import (
    AXIS5Packet,
    calculate_odd_parity,
)
from CocoTBFramework.components.axis5.axis5_slave import AXIS5Slave

# ----------------------------------------------------------------------
# AXIS5 odd parity - hand-computed golden vectors
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "data,num_bytes,expected",
    [
        # byte 0x00 has zero ones (even) -> odd parity bit must be 1
        (0x00000000, 4, 0xF),
        # byte 0xFF has eight ones (even) -> parity bit 1
        (0xFFFFFFFF, 4, 0xF),
        # byte0=0x01 (odd ones -> 0), bytes1-3=0x00 (even -> 1) => 0b1110
        (0x00000001, 4, 0xE),
        # byte0=0xFF (even -> 1), byte1=0x01 (odd -> 0),
        # byte2=0x02 (odd -> 0), byte3=0x03 (even -> 1) => 0b1001
        (0x030201FF, 4, 0x9),
        # byte0=0x78 (4 ones -> 1), byte1=0x56 (4 ones -> 1),
        # byte2=0x34 (3 ones -> 0), byte3=0x12 (2 ones -> 1) => 0b1011
        (0x12345678, 4, 0xB),
        # single byte: 0x07 has 3 ones (odd) -> parity bit 0
        (0x07, 1, 0x0),
        # 8 bytes, all zero -> all parity bits set
        (0x0000000000000000, 8, 0xFF),
    ],
)
def test_calculate_odd_parity_golden_vectors(data, num_bytes, expected):
    assert calculate_odd_parity(data, num_bytes) == expected


def test_odd_parity_makes_total_ones_odd():
    """Definition check: byte plus its parity bit always has odd popcount."""
    for data in (0x00, 0x5A, 0xA5, 0xFF, 0x80, 0x7F):
        parity = calculate_odd_parity(data, 1)
        total_ones = bin(data).count("1") + parity
        assert total_ones % 2 == 1


def test_axis5_packet_calculate_parity_is_odd():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=True)
    pkt.data = 0x00000001
    assert pkt.calculate_parity() == 0xE

    pkt.data = 0x030201FF
    assert pkt.calculate_parity() == 0x9


def test_axis5_check_parity_pass_and_fail():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=True)
    pkt.data = 0x12345678
    pkt.parity = pkt.calculate_parity()
    assert pkt.check_parity() is True

    # Corrupt one parity bit -> must fail
    pkt.parity = pkt.calculate_parity() ^ 0x1
    assert pkt.check_parity() is False


def test_axis5_check_parity_disabled_always_passes():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=False)
    pkt.data = 0xDEADBEEF
    assert pkt.check_parity() is True


def test_axis5_parity_width_follows_data_width():
    pkt64 = AXIS5Packet(data_width=64, enable_wakeup=False, enable_parity=True)
    pkt64.data = 0
    # 8 data bytes -> 8 parity bits, all-zero bytes -> all parity bits set
    assert pkt64.calculate_parity() == 0xFF


# ----------------------------------------------------------------------
# AXIS5Packet.copy() - must preserve constructor options
# ----------------------------------------------------------------------


def test_axis5_copy_preserves_constructor_options():
    pkt = AXIS5Packet(data_width=64, enable_wakeup=False, enable_parity=True)
    copied = pkt.copy()

    assert isinstance(copied, AXIS5Packet)
    assert copied.enable_parity is True
    assert copied.enable_wakeup is False
    assert copied.data_width == 64
    assert copied.parity_width == 8


def test_axis5_copy_preserves_fields_and_parity_check():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=True)
    pkt.data = 0x12345678
    pkt.last = 1
    pkt.wakeup = 1
    pkt.parity = pkt.calculate_parity() ^ 0x3  # corrupted parity

    copied = pkt.copy()

    assert copied.data == 0x12345678
    assert copied.last == 1
    assert copied.wakeup == 1
    assert copied.parity == pkt.parity
    # A copy of a corrupted packet must still FAIL the parity check
    # (previously the copy lost enable_parity and trivially passed)
    assert copied.check_parity() is False


def test_axis5_copy_of_good_packet_passes_parity():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=True)
    pkt.data = 0xCAFEF00D
    pkt.parity = pkt.calculate_parity()

    assert pkt.copy().check_parity() is True


# ----------------------------------------------------------------------
# AXISPacket helpers
# ----------------------------------------------------------------------


def _axis_config():
    return AXISFieldConfigs.create_default_axis_config()


def test_axis_packet_byte_count_follows_strobe():
    pkt = AXISPacket(field_config=_axis_config())
    pkt.data = 0x12345678
    pkt.strb = 0xF
    assert pkt.get_byte_count() == 4

    pkt.strb = 0x5
    assert pkt.get_byte_count() == 2

    pkt.strb = 0x0
    assert pkt.get_byte_count() == 0


def test_axis_packet_get_data_bytes_respects_strobe():
    pkt = AXISPacket(field_config=_axis_config())
    pkt.data = 0x44332211
    pkt.strb = 0b1010  # bytes 1 and 3 valid
    assert pkt.get_data_bytes() == [0x22, 0x44]


def test_axis_packet_set_data_bytes_packs_data_and_strobe():
    pkt = AXISPacket(field_config=_axis_config())
    pkt.set_data_bytes([0xAA, 0xBB, 0xCC])
    assert pkt.data == 0xCCBBAA
    assert pkt.strb == 0b111


def test_axis_packet_is_last():
    pkt = AXISPacket(field_config=_axis_config())
    assert pkt.is_last() is False
    pkt.last = 1
    assert pkt.is_last() is True


def test_create_axis_packet_factory_sets_fields():
    config = _axis_config()
    pkt = create_axis_packet(
        data=0xDEADBEEF, last=1, id=3, dest=2, user=1, field_config=config
    )
    assert pkt.data == 0xDEADBEEF
    assert pkt.last == 1
    assert pkt.id == 3
    assert pkt.dest == 2
    assert pkt.user == 1
    # strb auto-generated to all bytes enabled
    assert pkt.strb == (1 << config["strb"].bits) - 1


def test_axis5_to_axis4_packet_drops_extensions():
    pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=True)
    pkt.data = 0x11223344
    pkt.last = 1
    pkt.wakeup = 1
    pkt.parity = pkt.calculate_parity()

    axis4_pkt = pkt.to_axis4_packet()
    assert isinstance(axis4_pkt, AXISPacket)
    assert not isinstance(axis4_pkt, AXIS5Packet)
    assert axis4_pkt.data == 0x11223344
    assert axis4_pkt.last == 1
    assert "wakeup" not in axis4_pkt.fields
    assert "parity" not in axis4_pkt.fields


# ----------------------------------------------------------------------
# axis_factories must delegate to the AXIS classes (owner decree:
# GAXI is the workhorse, AXIS wraps it - factories return AXIS API)
# ----------------------------------------------------------------------


def test_axis_factories_reference_axis_classes():
    assert axis_factories.AXISMaster is AXISMaster
    assert axis_factories.AXISSlave is AXISSlave
    assert axis_factories.AXISMonitor is AXISMonitor
    # The raw GAXI classes must no longer be the factory construction targets
    for name in ("GAXIMaster", "GAXISlave", "GAXIMonitor"):
        assert not hasattr(axis_factories, name)


# ----------------------------------------------------------------------
# The GAXI receive pipeline must hand back protocol packet classes, not
# plain GAXIPacket (see GAXIComponentBase._build_packet). Behavioural
# coverage of the hook lives in test_axis_monitor_delegation.py.
# ----------------------------------------------------------------------


def test_axis_components_default_to_axis_packet_class():
    assert AXISMonitor._default_packet_class is AXISPacket
    assert AXISSlave._default_packet_class is AXISPacket


def test_axis5_components_default_to_axis5_packet_class():
    assert AXIS5Monitor._default_packet_class is AXIS5Packet
    assert AXIS5Slave._default_packet_class is AXIS5Packet
