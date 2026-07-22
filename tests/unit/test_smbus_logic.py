"""Unit tests for simulator-free SMBus BFM logic.

Covers:
- classify_sda_event: the pure START/STOP/IDLE decision extracted from the
  monitor/slave condition-detection wait loops (audit fix for mid-byte
  STOP / repeated-START detection).
- SMBusMonitor._parse_transaction: byte-stream framing into transaction
  types (exercised without a simulator via a stub entity).
- SMBusCRC: CRC-8 PEC calculation.

The trigger-driven wait loops themselves (_wait_scl_edge_or_condition,
_receive_byte_with_conditions, _receive_byte_or_condition) require a
running simulator and are not unit-testable here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from CocoTBFramework.components.smbus.smbus_components import (
    SMBusCRC,
    SMBusMonitor,
    classify_sda_event,
)
from CocoTBFramework.components.smbus.smbus_packet import (
    SMBusCondition,
    SMBusPacket,
    SMBusTransactionType,
)


# ---------------------------------------------------------------------------
# classify_sda_event
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scl_level, sda_after, expected",
    [
        # SDA falling while SCL high = START (or repeated START)
        (1, 0, SMBusCondition.START),
        # SDA rising while SCL high = STOP
        (1, 1, SMBusCondition.STOP),
        # SDA transitions while SCL low are normal data changes
        (0, 0, SMBusCondition.IDLE),
        (0, 1, SMBusCondition.IDLE),
    ],
)
def test_classify_sda_event(scl_level, sda_after, expected):
    """START/STOP per I2C/SMBus rules; data changes while SCL low are IDLE."""
    assert classify_sda_event(scl_level, sda_after) is expected


def test_classify_sda_event_non_binary_scl_is_idle():
    """X/Z SCL (reported as e.g. -1 or 2) must not be mistaken for high."""
    assert classify_sda_event(2, 1) is SMBusCondition.IDLE
    assert classify_sda_event(-1, 0) is SMBusCondition.IDLE


# ---------------------------------------------------------------------------
# SMBusMonitor._parse_transaction (pure byte-stream framing)
# ---------------------------------------------------------------------------

def _make_monitor() -> SMBusMonitor:
    """Build a monitor around a stub entity; no simulator needed."""
    entity = SimpleNamespace(smb_scl_i=object(), smb_sda_i=object())
    return SMBusMonitor(entity, "UnitTest_Monitor")


def _parse(bytes_received, read_write) -> SMBusPacket:
    """Run _parse_transaction over a raw byte stream (addr byte first)."""
    monitor = _make_monitor()
    packet = SMBusPacket(
        slave_addr=(bytes_received[0] >> 1) & 0x7F,
        read_write=read_write,
    )
    monitor._current_packet = packet
    monitor._bytes_received = list(bytes_received)
    monitor._parse_transaction()
    return packet


ADDR_WR = (0x50 << 1) | 0
ADDR_RD = (0x50 << 1) | 1


def test_parse_quick_command():
    packet = _parse([ADDR_WR], read_write=0)
    assert packet.trans_type is SMBusTransactionType.QUICK_CMD


def test_parse_send_byte():
    packet = _parse([ADDR_WR, 0xAB], read_write=0)
    assert packet.trans_type is SMBusTransactionType.SEND_BYTE
    assert packet.data == [0xAB]


def test_parse_recv_byte():
    packet = _parse([ADDR_RD, 0xCD], read_write=1)
    assert packet.trans_type is SMBusTransactionType.RECV_BYTE
    assert packet.data == [0xCD]


def test_parse_write_byte():
    packet = _parse([ADDR_WR, 0x10, 0xAB], read_write=0)
    assert packet.trans_type is SMBusTransactionType.WRITE_BYTE
    assert packet.command == 0x10
    assert packet.data == [0xAB]


def test_parse_write_word():
    packet = _parse([ADDR_WR, 0x10, 0x34, 0x12], read_write=0)
    assert packet.trans_type is SMBusTransactionType.WRITE_WORD
    assert packet.command == 0x10
    assert packet.data == [0x34, 0x12]


def test_parse_block_write():
    packet = _parse([ADDR_WR, 0x20, 0x03, 0x11, 0x22, 0x33], read_write=0)
    assert packet.trans_type is SMBusTransactionType.BLOCK_WRITE
    assert packet.command == 0x20
    assert packet.byte_count == 0x03
    assert packet.data == [0x11, 0x22, 0x33]


def test_parse_block_read():
    packet = _parse([ADDR_RD, 0x20, 0x02, 0xAA, 0xBB], read_write=1)
    assert packet.trans_type is SMBusTransactionType.BLOCK_READ
    assert packet.command == 0x20
    assert packet.byte_count == 0x02
    assert packet.data == [0xAA, 0xBB]


def test_parse_empty_stream_is_noop():
    """No bytes (aborted address byte) must not raise or mutate the packet."""
    monitor = _make_monitor()
    packet = SMBusPacket()
    monitor._current_packet = packet
    monitor._bytes_received = []
    monitor._parse_transaction()
    assert packet.trans_type is SMBusTransactionType.QUICK_CMD  # default


# ---------------------------------------------------------------------------
# SMBusCRC (PEC)
# ---------------------------------------------------------------------------

def test_crc8_known_vector():
    """CRC-8/SMBus (poly 0x07, init 0) of 0xC2 alone."""
    assert SMBusCRC.calculate([0x00]) == 0x00
    # Single byte 0x01: 8 shifts of poly 0x07 -> 0x07
    assert SMBusCRC.calculate([0x01]) == 0x07


def test_crc8_appended_pec_verifies_to_zero():
    """Appending the PEC to the message must yield CRC 0 (self-check)."""
    message = [ADDR_WR, 0x10, 0xAB]
    pec = SMBusCRC.calculate(message)
    assert SMBusCRC.calculate(message + [pec]) == 0
