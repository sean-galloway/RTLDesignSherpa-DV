# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# Module: test_flat_signal_resolver
# Purpose: The credited-flit families (CXS, CHI) bind through SignalResolver
#          like every other family: discovery by prefix / bus_name over the
#          spellings a DUT may use, partial signal_map override, hard failure
#          naming what was tried.
#
# Subsystem: framework
"""Owner ruling 2026-10-30: no family keeps a private ``prefix + name``
binder. CXS and the first CHI cut did, and every port spelled a little
differently needed a hand-written signal_map. These tests pin the resolver
path that replaced them, against a fake DUT (no simulator)."""
from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.protocol_types import PROTOCOL_TYPES
from CocoTBFramework.components.shared.signal_mapping_helper import (
    CHI_NODE_PORTS,
    FLAT_PROTOCOL_TYPES,
    PROTOCOL_SIGNAL_CONFIGS,
    SignalResolver,
)


class _Sig:
    def __init__(self):
        self.value = 0


class _Dut:
    _name = 'fake_dut'

    def __init__(self, *names):
        for n in names:
            setattr(self, n, _Sig())


def _resolve(dut, protocol, prefix='', bus_name='', signal_map=None):
    r = SignalResolver(protocol, dut, None, None, 'test', prefix=prefix, bus_name=bus_name, signal_map=signal_map)
    r.get_signal_lists()
    return r


CXS_PORT = ['m_cxs_valid', 'm_cxs_data', 'm_cxs_cntl', 'm_cxs_last', 'm_cxs_prcltype', 'm_cxs_crdgnt',
            'm_cxs_crdrtn', 'm_cxs_activereq', 'm_cxs_activeack', 'm_cxs_deacthint', 'm_cxs_validchk',
            'm_cxs_datachk', 'm_cxs_crdgntchk']


def test_flat_types_are_registered_both_halves():
    assert FLAT_PROTOCOL_TYPES <= PROTOCOL_TYPES
    assert FLAT_PROTOCOL_TYPES <= set(PROTOCOL_SIGNAL_CONFIGS)
    assert {f'chi_{n}_port' for n in CHI_NODE_PORTS} <= FLAT_PROTOCOL_TYPES
    for t in FLAT_PROTOCOL_TYPES:
        assert PROTOCOL_SIGNAL_CONFIGS[t]['flat'] is True


@pytest.mark.parametrize("prefix", ['m_cxs_', 'm_cxs', 'm_'])
def test_cxs_discovers_rtl_style_names(prefix):
    dut = _Dut(*CXS_PORT)
    r = _resolve(dut, 'cxs', prefix=prefix)
    for name in ('valid', 'data', 'cntl', 'last', 'prcltype', 'crdgnt', 'crdrtn', 'activereq', 'activeack',
                 'deacthint', 'validchk', 'datachk', 'crdgntchk'):
        assert r.get_signal(name) is getattr(dut, f'm_cxs_{name}'), name
    assert not r.has_signal('srcid') and not r.has_signal('user')


def test_cxs_discovers_spec_style_upper_case_and_underscored_names():
    dut = _Dut('CXSTXVALID', 'CXSTXDATA', 'CXSTXCRDGNT', 'CXSTXACTIVEREQ')
    r = _resolve(dut, 'cxs', prefix='CXSTX')
    assert r.get_signal('valid') is dut.CXSTXVALID and r.get_signal('activereq') is dut.CXSTXACTIVEREQ
    dut = _Dut('s_cxs_valid', 's_cxs_data', 's_cxs_crd_gnt', 's_cxs_crd_rtn', 's_cxs_active_req', 's_cxs_prcl_type')
    r = _resolve(dut, 'cxs', prefix='s_cxs_')
    assert r.get_signal('crdgnt') is dut.s_cxs_crd_gnt and r.get_signal('prcltype') is dut.s_cxs_prcl_type


def test_cxs_partial_signal_map_overrides_one_name_and_discovery_does_the_rest():
    dut = _Dut('m_cxs_valid', 'm_cxs_data', 'odd_credit_pin')
    r = _resolve(dut, 'cxs', prefix='m_cxs_', signal_map={'crdgnt': 'odd_credit_pin'})
    assert r.get_signal('crdgnt') is dut.odd_credit_pin and r.get_signal('valid') is dut.m_cxs_valid
    with pytest.raises(ValueError, match="unexpected keys"):
        _resolve(dut, 'cxs', prefix='m_cxs_', signal_map={'crdgrant': 'odd_credit_pin'})


def test_cxs_missing_required_names_what_was_tried():
    dut = _Dut('m_cxs_valid', 'm_cxs_data')
    with pytest.raises(ValueError) as e:
        _resolve(dut, 'cxs', prefix='m_cxs_')
    msg = str(e.value)
    assert 'crdgnt' in msg and 'm_cxs_crdgnt' in msg and 'm_cxs_crd_gnt' in msg


def _chi_names(prefix, node='rn_f', sep=''):
    tx = {'rn_f': ('req', 'rsp', 'dat'), 'hn_f': ('rsp', 'dat', 'snp')}[node]
    rx = {'rn_f': ('rsp', 'dat', 'snp'), 'hn_f': ('req', 'rsp', 'dat')}[node]
    names = []
    for d, chans in (('tx', tx), ('rx', rx)):
        for ch in chans:
            for sig in ('flitpend', 'flitv', 'flit', 'lcrdv'):
                names.append(f"{prefix}{d}{sep}{ch}{sep}{sig}")
    return names


def test_chi_rn_f_port_discovers_every_channel_signal():
    dut = _Dut(*_chi_names('rn_'), 'rn_txlinkactivereq', 'rn_txlinkactiveack', 'rn_rxlinkactivereq',
               'rn_rxlinkactiveack', 'rn_txsactive', 'rn_rxsactive')
    r = _resolve(dut, 'chi_rn_f_port', prefix='rn_')
    assert r.get_signal('txreqflitv') is dut.rn_txreqflitv
    assert r.get_signal('rxsnplcrdv') is dut.rn_rxsnplcrdv
    assert r.get_signal('txlinkactivereq') is dut.rn_txlinkactivereq
    assert r.get_signal('rxsactive') is dut.rn_rxsactive


def test_chi_port_accepts_underscored_and_upper_case_spellings():
    dut = _Dut(*_chi_names('u0_', sep='_'))
    r = _resolve(dut, 'chi_rn_f_port', prefix='u0_')
    assert r.get_signal('txreqflitv') is dut.u0_tx_req_flitv
    dut = _Dut(*[n.upper() for n in _chi_names('')])
    r = _resolve(dut, 'chi_rn_f_port')
    assert r.get_signal('rxdatflit') is dut.RXDATFLIT


def test_chi_link_signals_are_optional_but_flits_are_required():
    dut = _Dut(*_chi_names('rn_'))
    r = _resolve(dut, 'chi_rn_f_port', prefix='rn_')
    assert not r.has_signal('txlinkactivereq')
    with pytest.raises(ValueError, match="txsnpflit"):
        _resolve(_Dut(*_chi_names('hn_')), 'chi_hn_f_port', prefix='hn_')   # an RN-F port list, not an HN-F one


def test_chi_two_ports_on_one_dut_do_not_cross():
    dut = _Dut(*_chi_names('rn_'), *_chi_names('hn_', node='hn_f'))
    rn = _resolve(dut, 'chi_rn_f_port', prefix='rn_')
    hn = _resolve(dut, 'chi_hn_f_port', prefix='hn_')
    assert rn.get_signal('txreqflitv') is dut.rn_txreqflitv
    assert hn.get_signal('rxreqflitv') is dut.hn_rxreqflitv
    assert rn.get_signal('rxrspflitv') is not hn.get_signal('rxrspflitv')
