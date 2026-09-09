"""Unit tests for the Wishbone B4 BFMs that need no simulator: the packet,
the shared constants, and the bind-time signal resolution (data-name
aliases, optional ERR/RTY)."""
from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.wb4_common import (
    WB4_DATA_ALIASES,
    WB4_MASTER_DRIVEN,
    WB4_OPTIONAL_SIGNALS,
    WB4_SLAVE_DRIVEN,
    WB4_STATUS_ACK,
    WB4_STATUS_ERR,
    WB4_STATUS_RTY,
)
from CocoTBFramework.components.wb4.wb4_components import WB4SignalMixin, _status_of
from CocoTBFramework.components.wb4.wb4_packet import WB4Packet


class _Entity:
    """A DUT stand-in: only attribute names matter for binding."""
    def __init__(self, names):
        for n in names:
            setattr(self, n, object())


def _ports(prefix, dat_w='DAT_W', dat_r='DAT_R', extra=('ERR', 'RTY'), case=str.upper):
    base = ['CYC', 'STB', 'WE', 'ADR', 'SEL', 'STALL', 'ACK', dat_w, dat_r, *extra]
    return [f"{prefix}_{case(b)}" for b in base]


def test_constants_shape():
    assert isinstance(WB4_MASTER_DRIVEN, tuple) and isinstance(WB4_SLAVE_DRIVEN, tuple)
    assert set(WB4_OPTIONAL_SIGNALS) == {"ERR", "RTY"}
    assert set(WB4_DATA_ALIASES) == {"DAT_W", "DAT_R"}
    assert (WB4_STATUS_ACK, WB4_STATUS_ERR, WB4_STATUS_RTY) == (0, 1, 2)


def test_status_priority_err_over_rty_over_ack():
    assert _status_of(1, 0, 0) == WB4_STATUS_ACK
    assert _status_of(0, 1, 0) == WB4_STATUS_ERR
    assert _status_of(0, 0, 1) == WB4_STATUS_RTY
    assert _status_of(1, 1, 1) == WB4_STATUS_ERR
    assert _status_of(0, 0, 0) is None


def test_packet_defaults_and_formatting():
    p = WB4Packet(addr_width=16, data_width=32)
    assert p.sel == 0xF and p.status == 0 and p.direction == 'READ'
    p = WB4Packet(we=1, adr=0x1234, dat_w=0xDEADBEEF, sel=0x3, status=WB4_STATUS_RTY)
    assert p.direction == 'WRITE' and p.status_name == 'RTY'
    s = p.formatted(compact=True)
    assert 'WRITE' in s and 'DEADBEEF' in s and s.endswith('RTY')


def test_packet_compare_skips_timing_fields():
    a = WB4Packet(we=0, adr=8, count=1, start_time=10.0)
    b = WB4Packet(we=0, adr=8, count=2, start_time=99.0)
    assert a == b
    b.adr = 12
    assert a != b


def test_resolve_canonical_names():
    e = _Entity(_ports('m_wb'))
    req, opt, aliases = WB4SignalMixin._resolve(e, 'm_wb', None)
    assert set(req) == set(WB4_MASTER_DRIVEN) | set(WB4_SLAVE_DRIVEN) | {'DAT_W', 'DAT_R'}
    assert aliases == {'DAT_W': 'DAT_W', 'DAT_R': 'DAT_R'}
    assert opt == {'ERR': 'ERR', 'RTY': 'RTY'}


def test_resolve_dat_o_dat_i_and_lowercase():
    e = _Entity(_ports('s_wb', dat_w='dat_o', dat_r='dat_i', case=str.lower))
    _req, opt, aliases = WB4SignalMixin._resolve(e, 's_wb', None)
    assert aliases == {'DAT_W': 'dat_o', 'DAT_R': 'dat_i'}
    assert opt == {'ERR': 'err', 'RTY': 'rty'}


def test_resolve_without_err_rty_is_optional():
    e = _Entity(_ports('wb', extra=()))
    _req, opt, _aliases = WB4SignalMixin._resolve(e, 'wb', None)
    assert opt == {}


def test_resolve_missing_data_signal_raises():
    e = _Entity([f"wb_{n}" for n in ('CYC', 'STB', 'WE', 'ADR', 'SEL', 'STALL', 'ACK', 'DAT_W')])
    with pytest.raises(AttributeError, match='DAT_R'):
        WB4SignalMixin._resolve(e, 'wb', None)


def test_explicit_signal_list_is_verbatim():
    e = _Entity([])
    req, opt, aliases = WB4SignalMixin._resolve(e, 'x', ['A', 'B'])
    assert req == ['A', 'B'] and opt == [] and aliases == {}
