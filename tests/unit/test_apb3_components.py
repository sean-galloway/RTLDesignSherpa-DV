# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for APB3 components and packet."""

import pytest

from CocoTBFramework.components.apb3 import (
    APB3Master,
    APB3Monitor,
    APB3Packet,
    APB3Slave,
    create_apb3_components,
    create_apb3_master,
    create_apb3_monitor,
    create_apb3_slave,
)
from CocoTBFramework.components.apb3.apb3_packet import APB3Packet


def test_apb3_packet_field_config_omits_pstrb_pprot():
    pkt = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB)
    names = set(pkt.fields.keys())
    assert 'pwrite' in names
    assert 'paddr' in names
    assert 'pwdata' in names
    assert 'pstrb' not in names
    assert 'pprot' not in names


def test_apb3_packet_ignores_pstrb_pprot_kwargs():
    pkt = APB3Packet(pwrite=0, paddr=0x200, pstrb=0xF, pprot=7)
    assert pkt.fields['paddr'] == 0x200
    assert 'pstrb' not in pkt.fields
    assert 'pprot' not in pkt.fields


def test_apb3_packet_direction_derived_from_pwrite():
    write_pkt = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB)
    read_pkt = APB3Packet(pwrite=0, paddr=0x100)
    assert write_pkt.direction == 'WRITE'
    assert read_pkt.direction == 'READ'


def test_apb3_packet_formatted_compact_omits_pstrb_pprot():
    pkt = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB)
    compact = pkt.formatted(compact=True)
    assert 'strb' not in compact
    assert 'prot' not in compact


def test_apb3_packet_equality_considers_only_apb3_signals():
    a = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB, pslverr=0)
    b = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB, pslverr=0)
    assert a == b

    c = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xCD, pslverr=0)
    assert a != c


def test_apb3_packet_inequality_with_non_apb3packet():
    pkt = APB3Packet()
    assert pkt.__eq__(object()) is NotImplemented


def test_apb3_factory_functions_are_callable():
    # We cannot instantiate against a real DUT in a unit test, but we can
    # confirm the factory signatures and return types are wired.
    import inspect
    for func in (create_apb3_master, create_apb3_slave, create_apb3_monitor):
        sig = inspect.signature(func)
        params = list(sig.parameters)
        assert 'entity' in params
        assert 'title' in params
        assert 'prefix' in params
        assert 'clock' in params


def test_apb3_components_factory_is_importable():
    import inspect
    sig = inspect.signature(create_apb3_components)
    assert 'entity' in sig.parameters
    assert 'clock' in sig.parameters


@pytest.mark.parametrize("cls", [APB3Master, APB3Slave, APB3Monitor])
def test_apb3_bfms_inherit_from_apb4(cls):
    from CocoTBFramework.components.apb.apb_components import (
        APBMaster,
        APBMonitor,
        APBSlave,
    )
    parent = {
        APB3Master: APBMaster,
        APB3Slave: APBSlave,
        APB3Monitor: APBMonitor,
    }[cls]
    assert issubclass(cls, parent)
