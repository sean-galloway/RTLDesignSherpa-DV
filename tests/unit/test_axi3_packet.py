# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for AXI3 packets."""

import pytest

from CocoTBFramework.components.axi3.axi3_packet import AXI3Packet


def test_create_aw_packet_has_four_bit_len():
    pkt = AXI3Packet.create_aw_packet(id=1, addr=0x1000, len=15)
    assert pkt.id == 1
    assert pkt.addr == 0x1000
    assert pkt.len == 15
    assert pkt.get_channel_type() == 'AW'


def test_create_w_packet_has_wid():
    pkt = AXI3Packet.create_w_packet(id=5, data=0xDEADBEEF, last=1)
    assert pkt.id == 5
    assert pkt.get_channel_type() == 'W'


def test_aw_packet_channel_type_requires_data_absent():
    pkt = AXI3Packet.create_aw_packet(id=1, addr=0x1000, len=3)
    assert pkt.get_channel_type() == 'AW'


def test_ar_packet_channel_type():
    pkt = AXI3Packet.create_ar_packet(id=2, addr=0x2000, len=7)
    assert pkt.get_channel_type() == 'AR'


def test_b_packet_channel_type():
    pkt = AXI3Packet.create_b_packet(id=3, resp=2)
    assert pkt.get_channel_type() == 'B'


def test_r_packet_channel_type():
    pkt = AXI3Packet.create_r_packet(id=4, data=0x12345678, resp=0, last=1)
    assert pkt.get_channel_type() == 'R'


def test_validate_rejects_bad_lock():
    pkt = AXI3Packet.create_aw_packet(lock=3)
    valid, msg = pkt.validate_axi3_protocol()
    assert not valid
    assert 'lock' in msg


def test_validate_w_requires_last():
    pkt = AXI3Packet.create_w_packet(last=0)
    valid, msg = pkt.validate_axi3_protocol()
    assert valid
    assert msg == ""


def test_burst_info_returns_sixteen_beats_for_len_fifteen():
    pkt = AXI3Packet.create_aw_packet(addr=0x1000, len=15, size=2)
    info = pkt.get_burst_info()
    assert info['burst_length'] == 16
    assert info['bytes_per_beat'] == 4


def test_response_info_flags_errors():
    pkt = AXI3Packet.create_r_packet(resp=2, last=1)
    info = pkt.get_response_info()
    assert info['is_error']
    assert not info['is_exclusive']


def test_string_representations_include_channel():
    aw = AXI3Packet.create_aw_packet(id=1, addr=0x1000, len=3)
    assert 'AW:' in str(aw)
    w = AXI3Packet.create_w_packet(id=1, data=0xAB, last=1)
    assert 'W:' in str(w)


def test_create_simple_write_packets():
    from CocoTBFramework.components.axi3.axi3_packet import create_simple_write_packets
    aw, w = create_simple_write_packets(1, 0x1000, 0x12345678)
    assert aw.get_channel_type() == 'AW'
    assert w.get_channel_type() == 'W'
    assert aw.id == 1
    assert w.id == 1


def test_create_simple_read_packet():
    from CocoTBFramework.components.axi3.axi3_packet import create_simple_read_packet
    ar = create_simple_read_packet(2, 0x2000)
    assert ar.get_channel_type() == 'AR'
    assert ar.id == 2
