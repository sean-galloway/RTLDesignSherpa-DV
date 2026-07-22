"""Unit tests for MemoryModel.

The APB5Slave bug fixed in #15 Phase B was:
    self.mem.write(line_idx, integer, strobes)   # wrong: needs byte addr + bytearray
    self.mem.read(line_idx)                       # wrong: missing length

The tests below pin down the actual MemoryModel API contract so that class
of bug can't recur silently.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.memory_model import MemoryModel


@pytest.fixture
def mem():
    return MemoryModel(num_lines=4, bytes_per_line=4)


def test_write_requires_bytearray_not_int(mem):
    """Regression for APB5Slave bug: passing int as data must fail loudly."""
    with pytest.raises(TypeError, match="Data must be a bytearray"):
        mem.write(0, 0xDEADBEEF, strobe=0xF)


def test_read_requires_length_argument(mem):
    """Regression for APB5Slave bug: read() without length is a TypeError."""
    with pytest.raises(TypeError):
        mem.read(0)  # missing required length


def test_write_then_read_roundtrip(mem):
    """Round-trip a 4-byte value through write/read using the correct API."""
    data = bytearray([0xEF, 0xBE, 0xAD, 0xDE])  # little-endian 0xDEADBEEF
    mem.write(0, data, strobe=0xF)
    out = mem.read(0, 4)
    assert bytes(out) == bytes(data)


def test_write_with_partial_strobe(mem):
    """Strobe=0b0011 should only write the low two bytes."""
    mem.write(0, bytearray([0xFF, 0xFF, 0xFF, 0xFF]), strobe=0xF)
    mem.write(0, bytearray([0x11, 0x22, 0x33, 0x44]), strobe=0b0011)
    out = bytes(mem.read(0, 4))
    assert out == bytes([0x11, 0x22, 0xFF, 0xFF])


def test_write_with_matching_full_strobe_ok(mem):
    """A strobe with exactly one enable bit per data byte is accepted."""
    data = bytearray([0x11, 0x22, 0x33, 0x44])
    mem.write(0, data, strobe=0b1111)  # 4 bits for 4 bytes
    assert bytes(mem.read(0, 4)) == bytes(data)


def test_write_strobe_wider_than_data_rejected(mem):
    """Strobe with enable bits beyond len(data) must fail loudly.

    Strobe is 1 bit PER BYTE: a 4-byte write accepts at most a 4-bit strobe.
    The old check compared data bits (data_len * 8) to strobe bits, silently
    accepting over-wide strobes and truncating them.
    """
    with pytest.raises(ValueError, match="byte-enable bits"):
        mem.write(0, bytearray([0xAA, 0xBB]), strobe=0b111)  # 3 bits, 2 bytes
    with pytest.raises(ValueError, match="byte-enable bits"):
        mem.write(0, bytearray([0xAA, 0xBB, 0xCC, 0xDD]), strobe=0x1F)


def test_write_partial_strobe_writes_only_enabled_bytes(mem):
    """Partial strobe updates exactly the enabled bytes, preserves the rest."""
    mem.write(0, bytearray([0xA0, 0xA1, 0xA2, 0xA3]), strobe=0xF)
    mem.write(0, bytearray([0x50, 0x51, 0x52, 0x53]), strobe=0b0101)
    out = bytes(mem.read(0, 4))
    assert out == bytes([0x50, 0xA1, 0x52, 0xA3])


def test_write_zero_strobe_writes_nothing(mem):
    """Strobe of 0 leaves memory untouched."""
    mem.write(0, bytearray([0xEE, 0xEE, 0xEE, 0xEE]), strobe=0xF)
    mem.write(0, bytearray([0x00, 0x00, 0x00, 0x00]), strobe=0)
    assert bytes(mem.read(0, 4)) == bytes([0xEE, 0xEE, 0xEE, 0xEE])


def test_read_out_of_bounds_raises(mem):
    with pytest.raises(ValueError, match="exceeds memory bounds"):
        mem.read(15, 4)  # mem is 16 bytes total


def test_write_out_of_bounds_raises(mem):
    with pytest.raises(ValueError, match="exceeds memory bounds"):
        mem.write(15, bytearray([0, 0, 0, 0]), strobe=0xF)


def test_integer_to_bytearray_roundtrip(mem):
    """integer_to_bytearray + bytearray_to_integer is identity."""
    value = 0x12345678
    ba = mem.integer_to_bytearray(value, byte_length=4)
    assert isinstance(ba, (bytearray, bytes))
    assert mem.bytearray_to_integer(ba) == value


def test_expand_grows_memory(mem):
    """expand() increases num_lines and size; new region zero-initialized."""
    original_size = mem.size
    mem.expand(additional_lines=2)
    assert mem.size == original_size + 2 * mem.bytes_per_line
    # New region should be zero
    out = bytes(mem.read(original_size, 4))
    assert out == bytes([0, 0, 0, 0])


def test_preset_values_initialize_memory():
    """Preset values should be readable immediately after construction."""
    preset = [0xAA, 0xBB, 0xCC, 0xDD] + [0] * 12  # 16 bytes
    mem = MemoryModel(num_lines=4, bytes_per_line=4, preset_values=preset)
    assert bytes(mem.read(0, 4)) == bytes([0xAA, 0xBB, 0xCC, 0xDD])


def test_reset_to_preset_restores_initial_values():
    preset = [0xAA] * 4 + [0] * 12
    mem = MemoryModel(num_lines=4, bytes_per_line=4, preset_values=preset)
    mem.write(0, bytearray([0xFF, 0xFF, 0xFF, 0xFF]), strobe=0xF)
    mem.reset(to_preset=True)
    assert bytes(mem.read(0, 4)) == bytes([0xAA, 0xAA, 0xAA, 0xAA])
