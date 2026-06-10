"""Unit tests for DFI packet types (issue #16)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_packet import (
    DFIControlPacket,
    DFIReadDataPacket,
    DFIWriteDataPacket,
    DRAMCommand,
)
from CocoTBFramework.components.dfi.dfi_signals import MemoryType


# ---------------------------------------------------------------------
# DRAMCommand encoding via DFIControlPacket.from_command
# ---------------------------------------------------------------------


def test_deselect_holds_cs_n_high():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.DESEL, memory_type=MemoryType.DDR3,
    )
    assert pkt.cs_n == 1  # CS_n deasserted = no command


def test_activate_encoding_ras_low_others_high():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.ACT, memory_type=MemoryType.DDR3,
        address=0x1234, bank=2,
    )
    assert pkt.cs_n == 0
    assert pkt.ras_n == 0   # ACT asserts RAS
    assert pkt.cas_n == 1
    assert pkt.we_n == 1
    assert pkt.address == 0x1234
    assert pkt.bank == 2


def test_read_encoding_cas_low_we_high():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.RD, memory_type=MemoryType.DDR3,
        bank=3, address=0x40,
    )
    assert pkt.ras_n == 1
    assert pkt.cas_n == 0
    assert pkt.we_n == 1


def test_write_encoding_cas_low_we_low():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.WR, memory_type=MemoryType.DDR3,
    )
    assert pkt.ras_n == 1
    assert pkt.cas_n == 0
    assert pkt.we_n == 0


def test_precharge_encoding_ras_we_low():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.PRE, memory_type=MemoryType.DDR3,
    )
    assert pkt.ras_n == 0
    assert pkt.cas_n == 1
    assert pkt.we_n == 0


def test_refresh_encoding_ras_cas_low():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.REF, memory_type=MemoryType.DDR3,
    )
    assert pkt.ras_n == 0
    assert pkt.cas_n == 0
    assert pkt.we_n == 1


def test_mrs_all_three_low():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.MRS, memory_type=MemoryType.DDR3,
    )
    assert pkt.ras_n == 0
    assert pkt.cas_n == 0
    assert pkt.we_n == 0


# ---------------------------------------------------------------------
# Auto-precharge / all-banks encoded in addr[10]
# ---------------------------------------------------------------------


def test_read_with_auto_precharge_sets_addr_bit10():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.RD, memory_type=MemoryType.DDR3,
        address=0x40, auto_precharge=True,
    )
    assert pkt.address == (0x40 | (1 << 10))


def test_read_without_auto_precharge_leaves_addr_bit10_clear():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.RD, memory_type=MemoryType.DDR3,
        address=0x40, auto_precharge=False,
    )
    assert pkt.address == 0x40


def test_precharge_all_banks_sets_addr_bit10():
    pkt = DFIControlPacket.from_command(
        DRAMCommand.PREA, memory_type=MemoryType.DDR3, all_banks=True,
    )
    assert pkt.address & (1 << 10)


# ---------------------------------------------------------------------
# LPDDR2 special-case
# ---------------------------------------------------------------------


def test_lpddr2_command_helper_raises():
    """LPDDR2 uses the CA encoding instead of the DDR RAS/CAS/WE signals."""
    with pytest.raises(NotImplementedError, match="LPDDR2"):
        DFIControlPacket.from_command(
            DRAMCommand.RD, memory_type=MemoryType.LPDDR2,
        )


# ---------------------------------------------------------------------
# Default-construct semantics (idle bus state)
# ---------------------------------------------------------------------


def test_default_control_packet_is_idle():
    """Default values should match the spec's deasserted/idle state."""
    pkt = DFIControlPacket()
    assert pkt.cs_n == 1     # CS_n high = no command
    assert pkt.ras_n == 1
    assert pkt.cas_n == 1
    assert pkt.we_n == 1
    assert pkt.reset_n == 1  # not in reset


def test_default_write_data_packet_inactive():
    pkt = DFIWriteDataPacket()
    assert pkt.wrdata_en == 0  # data invalid


def test_default_read_data_packet_inactive():
    pkt = DFIReadDataPacket()
    assert pkt.rddata_valid == 0
