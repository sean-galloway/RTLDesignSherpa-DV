# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_flits
# Purpose: CHI flit field layouts (IHI 0050H Tables B13.6 to B13.9) and the
#          Packet subclasses that pack to / unpack from one flit word
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI flits.

Four :class:`Packet` subclasses, one per channel, each with a cached
:class:`FieldConfig` built per :class:`CHIConfig`. Fields are added in the
order the spec tables list them, which (``FieldConfig`` default: the first
field added sits at bit 0) puts them at the table's "starting at bit 0"
positions. ``pack()`` / ``unpack()`` honour those positions, so the integer
is exactly ``REQFLIT[(R-1):0]`` on the wire. ``tests/unit/test_chi_flits.py``
checks every channel's total against the table totals and a field's bits
against the table arithmetic.

Shared bits. The spec reuses a field's bits for another field in other
message types: ReturnNID / StashNID / DataTarget share one slot, and so on.
Each slot is ONE field here, named for its first-listed use, and the other
names are aliases (``flit.stashnid`` reads the ``returnnid`` field). The
alias map is :data:`ALIASES`. Sub-fields that live inside a wider slot
(``DataPull`` = FwdState[0] in RSP, ``PBHA[3:0]`` in SNP FwdNID) are not
aliased; set them by value.
"""

from typing import Dict, Optional

from ..shared.field_config import FieldConfig, FieldDefinition
from ..shared.packet import Packet
from .chi_config import CHIConfig
from .chi_opcodes import DatOpcode, ReqOpcode, RspOpcode, SnpOpcode, opcode_name, req_opcode_name

CHANNELS = ('req', 'rsp', 'snp', 'dat')


def _enc(enum):
    return {int(m): m.name for m in enum}


def _field(name, bits, enc=None, desc=''):
    if bits <= 0:
        return None
    return FieldDefinition(name=name, bits=bits, default=0, format='hex',
                           display_width=(bits + 3) // 4, encoding=enc, description=desc)


# ---------------------------------------------------------------------------
# Layouts: (name, width) in spec order, bit 0 first. Width 0 = absent.
# ---------------------------------------------------------------------------
def req_layout(cfg: CHIConfig):
    """Table B13.6 Request flit."""
    n = cfg.nodeid_width
    return [
        ('qos', 4), ('tgtid', n), ('srcid', n), ('txnid', 12),
        ('returnnid', n),            # ReturnNID / StashNID / {MBZ, DataTarget[6:0]}
        ('stashnidvalid', 1),        # StashNIDValid / Endian / Deep / PrefetchTgtHint
        ('returntxnid', 12),         # ReturnTxnID / {6'b0, StashLPIDValid, StashLPID[4:0]}
        ('opcode', 7), ('multireq', 1),
        ('size', 3),                 # NumReq[2:0] when MultiReq = 1, else Size
        ('numreq_hi', 3),            # NumReq[5:3] when MultiReq = 1, else MBZ
        ('addr', cfg.addr_width), ('pas', 3), ('likelyshared', 1), ('allowretry', 1),
        ('order', 2), ('pcrdtype', 4), ('memattr', 4),
        ('snpattr', 1),              # SnpAttr / DoDWT
        ('lpid', 8),                 # {3'b0, LPID[4:0]} / PGroupID / StashGroupID / TagGroupID
        ('excl', 1),                 # Excl / SnoopMe / CAH
        ('expcompack', 1), ('tagop', 2), ('tracetag', 1),
        ('mpam', cfg.mpam_width), ('pbha', cfg.pbha_width),
        ('mecid', cfg.mecid_or_streamid_width),   # MECID / StreamID, Max(E, R)
        ('secsid1', cfg.secsid1_width), ('rsvdc', cfg.req_rsvdc_width),
    ]


def rsp_layout(cfg: CHIConfig):
    """Table B13.7 Response flit."""
    n = cfg.nodeid_width
    return [
        ('qos', 4), ('tgtid', n), ('srcid', n), ('txnid', 12), ('opcode', 5),
        ('resperr', 2), ('resp', 3),
        ('fwdstate', 3),             # FwdState[2:0] / {2'b0, DataPull}
        ('cbusy', 3),
        ('dbid', 12),                # DBID / {4'b0, PGroupID} / StashGroupID / TagGroupID
        ('pcrdtype', 4), ('tagop', 2), ('tracetag', 1), ('cachelineid', 6),
    ]


def snp_layout(cfg: CHIConfig):
    """Table B13.8 Snoop flit."""
    n = cfg.nodeid_width
    return [
        ('qos', 4), ('srcid', n), ('txnid', 12),
        ('fwdnid', n),               # FwdNID / {MBZ, PBHA[3:0]}
        ('fwdtxnid', 12),            # FwdTxnID / StashLPID group / {4'b0, VMIDExt}
        ('opcode', 5), ('addr', cfg.snp_addr_width), ('pas', 3),
        ('donotgotosd', 1), ('rettosrc', 1), ('tracetag', 1),
        ('mpam', cfg.mpam_width), ('mecid', cfg.mecid_width),
    ]


def dat_layout(cfg: CHIConfig):
    """Table B13.9 Data flit."""
    n = cfg.nodeid_width
    return [
        ('qos', 4), ('tgtid', n), ('srcid', n), ('txnid', 12),
        ('homenid', n),              # HomeNID / {MBZ, MismatchedMECID, PBHA[3:0]}
        ('opcode', 4), ('resperr', 2), ('resp', 3),
        ('datasource', 8),           # DataSource[7:0] / {5'b0, FwdState[2:0]}
        ('datapull', 1), ('cbusy', 3), ('mecid', cfg.mecid_width),
        ('dbid', 16),                # {4'b0, DBID[11:0]}
        ('ccid', 2), ('dataid', 2), ('cachelineid', 6), ('tagop', 2),
        ('tag', cfg.tag_width), ('tu', cfg.tu_width), ('tracetag', 1), ('cah', 1),
        ('numdat', 2), ('replicate', 1), ('rsvdc', cfg.dat_rsvdc_width),
        ('be', cfg.be_width), ('data', cfg.data_width),
        ('datacheck', cfg.data_check_width), ('poison', cfg.poison_width),
    ]


LAYOUTS = {'req': req_layout, 'rsp': rsp_layout, 'snp': snp_layout, 'dat': dat_layout}

# Whole-slot aliases only. A name that is a SUB-field of a wider slot
# (DataPull = RSP FwdState[0], FwdState = DAT DataSource[2:0], PBHA[3:0] in
# SNP FwdNID / DAT HomeNID, StashLPID inside ReturnTxnID / FwdTxnID) is not
# aliased: reading it through the slot would also return the other bits.
ALIASES: Dict[str, Dict[str, str]] = {
    'req': {'stashnid': 'returnnid', 'datatarget': 'returnnid',
            'endian': 'stashnidvalid', 'deep': 'stashnidvalid', 'prefetchtgthint': 'stashnidvalid',
            'dodwt': 'snpattr',
            'pgroupid': 'lpid', 'stashgroupid': 'lpid', 'taggroupid': 'lpid',
            'snoopme': 'excl', 'cah': 'excl', 'streamid': 'mecid'},
    'rsp': {'pgroupid': 'dbid', 'stashgroupid': 'dbid', 'taggroupid': 'dbid'},
    'snp': {'vmidext': 'fwdtxnid'},
    'dat': {},
}

_OPCODE_ENC = {'req': lambda: {int(m): m.name for m in ReqOpcode},
               'rsp': lambda: _enc(RspOpcode), 'snp': lambda: _enc(SnpOpcode),
               'dat': lambda: _enc(DatOpcode)}


def build_field_config(channel: str, cfg: CHIConfig) -> FieldConfig:
    fc = FieldConfig()
    for name, bits in LAYOUTS[channel](cfg):
        fd = _field(name, bits, enc=_OPCODE_ENC[channel]() if name == 'opcode' else None)
        if fd is not None:
            fc.add_field(fd)
    assert fc.total_bits == cfg.flit_width(channel), \
        f"{channel} layout is {fc.total_bits} bits, Table B13 says {cfg.flit_width(channel)}"
    return fc


# ---------------------------------------------------------------------------
# Flits
# ---------------------------------------------------------------------------
class CHIFlit(Packet):
    """One CHI flit on one channel. ``channel`` is 'req' | 'rsp' | 'snp' | 'dat'."""

    channel: str = ''
    _FIELD_CONFIGS: dict = {}

    def __init__(self, cfg: CHIConfig, field_config: Optional[FieldConfig] = None,
                 skip_compare_fields=None, **kwargs):
        object.__setattr__(self, 'cfg', cfg)
        object.__setattr__(self, 'count', kwargs.pop('count', 0))
        if field_config is None:
            field_config = self.create_field_config(cfg)
        if skip_compare_fields is None:
            skip_compare_fields = ['start_time', 'end_time', 'count']
        aliases = ALIASES[self.channel]
        kwargs = {aliases.get(k, k): v for k, v in kwargs.items()}
        super().__init__(field_config, skip_compare_fields, **kwargs)

    @classmethod
    def create_field_config(cls, cfg: CHIConfig) -> FieldConfig:
        key = (cls.channel, cfg)
        fc = CHIFlit._FIELD_CONFIGS.get(key)
        if fc is None:
            fc = build_field_config(cls.channel, cfg)
            CHIFlit._FIELD_CONFIGS[key] = fc
        return fc

    @classmethod
    def from_word(cls, cfg: CHIConfig, word: int, **extra):
        return cls(cfg, **extra).unpack(word)

    def __getattr__(self, name):
        alias = ALIASES[self.channel].get(name) if self.channel else None
        if alias is not None:
            return self.fields[alias]
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        alias = ALIASES[self.channel].get(name) if self.channel else None
        super().__setattr__(alias or name, value)

    @property
    def width(self):
        return self.field_config.total_bits

    @property
    def is_lcrd_return(self):
        """B13.11: a Link flit (LCrdReturn) has opcode 0 on every channel."""
        return int(self.fields.get('opcode', 0)) == 0

    @property
    def opcode_name(self):
        return opcode_name(self.channel, self.fields.get('opcode', 0))

    def __repr__(self):
        f = self.fields
        ids = ' '.join(f"{k}={f[k]:#x}" for k in ('tgtid', 'srcid', 'txnid') if k in f)
        extra = ''
        if self.channel == 'req':
            extra = f" addr={f['addr']:#x} size={f['size']} ecak={f['expcompack']}"
        elif self.channel == 'snp':
            extra = f" addr={f['addr'] << 3:#x}"
        elif self.channel in ('rsp', 'dat'):
            extra = f" resp={f['resp']} err={f['resperr']} dbid={f['dbid']:#x}"
            if self.channel == 'dat':
                extra += f" dataid={f['dataid']}"
        return f"{type(self).__name__}({self.opcode_name} {ids}{extra})"

    __str__ = __repr__


class CHIReqFlit(CHIFlit):
    channel = 'req'

    @property
    def opcode_enum(self):
        return req_opcode_name(self.fields['opcode'])


class CHIRspFlit(CHIFlit):
    channel = 'rsp'


class CHISnpFlit(CHIFlit):
    channel = 'snp'

    @property
    def byte_addr(self):
        """The snooped address: SNP Addr is Req Addr[RAW-1:3] (B13.10.20)."""
        return int(self.fields['addr']) << 3


class CHIDatFlit(CHIFlit):
    channel = 'dat'

    def data_bytes(self) -> bytes:
        """Payload as DW/8 little-endian bytes (byte n = Data[8n+7:8n])."""
        return int(self.fields['data']).to_bytes(self.cfg.data_width // 8, 'little')

    def set_data_bytes(self, payload: bytes):
        self.fields['data'] = int.from_bytes(bytes(payload).ljust(self.cfg.data_width // 8, b'\0'), 'little')
        return self


FLIT_CLASSES = {'req': CHIReqFlit, 'rsp': CHIRspFlit, 'snp': CHISnpFlit, 'dat': CHIDatFlit}


def flit_class(channel: str):
    return FLIT_CLASSES[channel]


__all__ = ['CHANNELS', 'LAYOUTS', 'ALIASES', 'build_field_config', 'CHIFlit', 'CHIReqFlit',
           'CHIRspFlit', 'CHISnpFlit', 'CHIDatFlit', 'FLIT_CLASSES', 'flit_class',
           'req_layout', 'rsp_layout', 'snp_layout', 'dat_layout']
