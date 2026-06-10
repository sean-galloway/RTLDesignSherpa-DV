"""Unit tests for packet construction (the protocol-specific subclasses).

Critical for #15 because the `_build_packet` hook overrides construct
APBPacket vs APB5Packet from the same call site — the constructors must
accept the kwargs that the hook passes.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.apb5.apb5_packet import APB5Packet


# ----------------------------------------------------------------------
# APBPacket — what APBMonitor._build_packet and APBSlave._build_packet pass
# ----------------------------------------------------------------------


def test_apb_packet_constructs_with_monitor_hook_kwargs():
    """Exact kwargs APBMonitor._build_packet passes."""
    pkt = APBPacket(
        start_time=12.5,
        count=1,
        pwrite=1,
        paddr=0x1000,
        pwdata=0xDEADBEEF,
        prdata=0,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
    )
    assert pkt.fields["pwrite"] == 1
    assert pkt.fields["paddr"] == 0x1000
    assert pkt.fields["pwdata"] == 0xDEADBEEF


def test_apb_packet_direction_decodes_pwrite():
    """direction attribute should be 'WRITE' when pwrite=1."""
    pkt = APBPacket(pwrite=1, paddr=0)
    assert pkt.direction == "WRITE"

    pkt_read = APBPacket(pwrite=0, paddr=0)
    assert pkt_read.direction == "READ"


def test_apb_packet_formatted_compact_returns_string():
    pkt = APBPacket(pwrite=1, paddr=0x100, pwdata=0xABCD)
    formatted = pkt.formatted(compact=True)
    assert isinstance(formatted, str)
    assert len(formatted) > 0


# ----------------------------------------------------------------------
# APB5Packet — what APB5Monitor._build_packet and APB5Slave._build_packet pass
# ----------------------------------------------------------------------


def test_apb5_packet_constructs_with_extension_fields():
    """The hook passes USER/WAKEUP fields — constructor must accept them."""
    pkt = APB5Packet(
        data_width=32,
        addr_width=12,
        strb_width=4,
        auser_width=4,
        wuser_width=4,
        ruser_width=4,
        buser_width=4,
        start_time=100.0,
        count=1,
        pwrite=1,
        paddr=0x200,
        pwdata=0x1234,
        prdata=0,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        pauser=5,
        pwuser=6,
        pruser=7,
        pbuser=8,
        wakeup=1,
    )
    assert pkt.fields["pauser"] == 5
    assert pkt.fields["pwuser"] == 6
    assert pkt.fields["pruser"] == 7
    assert pkt.fields["pbuser"] == 8


def test_apb5_packet_accepts_apb4_subset_kwargs():
    """APB5Packet should accept APB4-only kwargs (zero values for extensions)."""
    pkt = APB5Packet(
        data_width=32,
        addr_width=12,
        strb_width=4,
        auser_width=4,
        wuser_width=4,
        ruser_width=4,
        buser_width=4,
        pwrite=0,
        paddr=0x300,
    )
    # Extensions should default to 0
    assert pkt.fields.get("pauser", 0) == 0
    assert pkt.fields.get("pruser", 0) == 0


def test_apb5_packet_formatted_returns_string():
    pkt = APB5Packet(
        data_width=32, addr_width=12, strb_width=4,
        auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
        pwrite=1, paddr=0x400, pwdata=0xCAFE,
    )
    s = pkt.formatted(compact=True)
    assert isinstance(s, str) and s
