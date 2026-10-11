# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Inheritance and signal-set tests for APB3 BFMs (issue #87)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.apb.apb_components import APBMaster, APBMonitor, APBSlave
from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.apb3.apb3_components import APB3Master, APB3Monitor, APB3Slave
from CocoTBFramework.components.apb3.apb3_packet import APB3Packet


class _StubBus:
    """Minimal bus stub that satisfies hasattr() / getattr() checks."""

    def __init__(self, present_signals: set[str] | None = None,
                 signal_values: dict[str, int] | None = None):
        self._present = present_signals or set()
        self._values = signal_values or {}

    def __getattr__(self, name: str):
        if name in self._present:
            sig = _StubSignal(self._values.get(name, 0))
            setattr(self, name, sig)
            return sig
        raise AttributeError(name)


class _StubSignal:
    def __init__(self, integer_value: int = 0):
        self.value = _StubValue(integer_value)

    def setimmediatevalue(self, v):
        pass


class _StubValue:
    def __init__(self, integer_value: int, width: int = 32):
        self.integer = integer_value
        self.is_resolvable = True
        self._width = width

    def __int__(self):
        return self.integer


def _make_apb3_master_stub():
    inst = APB3Master.__new__(APB3Master)
    inst.bus = _StubBus(present_signals={"PSLVERR"})
    inst.bus_width = 32
    inst.addr_width = 12
    inst.strb_bits = 4
    return inst


def _make_apb3_slave_stub():
    inst = APB3Slave.__new__(APB3Slave)
    inst.bus = _StubBus(present_signals={"PSLVERR"})
    inst.bus_width = 32
    inst.addr_width = 12
    inst.strb_bits = 4
    return inst


def test_apb3_monitor_inherits_apb_monitor():
    assert issubclass(APB3Monitor, APBMonitor)


def test_apb3_master_inherits_apb_master():
    assert issubclass(APB3Master, APBMaster)


def test_apb3_slave_inherits_apb_slave():
    assert issubclass(APB3Slave, APBSlave)


def test_apb3_monitor_build_packet_returns_apb3packet():
    stub = APB3Monitor.__new__(APB3Monitor)
    stub.bus_width = 32
    stub.addr_width = 12
    stub.bus = _StubBus()

    pkt = stub._build_packet(
        start_time=0.0,
        count=1,
        pwrite=1,
        paddr=0x10,
        pwdata=0xFF,
        prdata=0,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        direction="WRITE",
    )
    assert isinstance(pkt, APB3Packet)
    assert not isinstance(pkt, APBPacket) or type(pkt) is APB3Packet
    assert 'pstrb' not in pkt.fields
    assert 'pprot' not in pkt.fields


def test_apb3_slave_build_packet_returns_apb3packet():
    stub = _make_apb3_slave_stub()
    pkt = APB3Slave._build_packet(
        stub,
        start_time=50.0,
        count=1,
        pwrite=0,
        paddr=0x200,
        pwdata=0,
        prdata=0xBEEF,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        direction="READ",
        extension_inputs={},
        rand_values={"ready": 0, "error": 0},
    )
    assert isinstance(pkt, APB3Packet)
    assert 'pstrb' not in pkt.fields
    assert 'pprot' not in pkt.fields


@pytest.mark.asyncio
async def test_apb3_master_write_rejects_strb():
    stub = _make_apb3_master_stub()
    with pytest.raises(ValueError, match="PSTRB"):
        await APB3Master.write(stub, 0x100, 0x1234, strb=0xF)


@pytest.mark.asyncio
async def test_apb3_master_write_rejects_pprot():
    stub = _make_apb3_master_stub()
    with pytest.raises(ValueError, match="PPROT"):
        await APB3Master.write(stub, 0x100, 0x1234, pprot=1)


@pytest.mark.asyncio
async def test_apb3_master_read_rejects_pprot():
    stub = _make_apb3_master_stub()
    with pytest.raises(ValueError, match="PPROT"):
        await APB3Master.read(stub, 0x100, pprot=1)


def test_apb3_packet_equality_ignores_pstrb_pprot():
    a = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB, pslverr=0)
    b = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB, pslverr=0)
    assert a == b
