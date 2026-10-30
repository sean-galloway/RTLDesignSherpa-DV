# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_transaction
# Purpose: One CHI request's life from issue to completion (IHI 0050H B2.3
#          flows, B2.4 identifiers, B2.7.3 CompAck, B2.9.4 packetization,
#          B2.10 retry), plus the Requester- and Completer-side trackers
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI transaction tracking, pure Python (no cocotb).

:class:`CHITransaction` is a request plus the legal-sequence rules of the
B2.3 flows for its class. A BFM feeds it every RSP / DAT flit addressed to
its TxnID and gets back :class:`Action` objects: send a CompAck, send the
write data, re-send after a retry, done, or a protocol error with the
sentence that names the rule. Nothing here touches a signal.

:class:`RequesterTracker` keys the in-flight transactions of one SrcID by
TxnID and runs the B2.10 retry machinery (RetryAck / PCrdGrant / banked
credits). :class:`CompleterTracker` is the Home side: requests keyed by
(SrcID, TxnID), DBID allocation, and the rendezvous of WriteData and CompAck
(whose TxnID is the DBID, B2.4.3) back to the request.

Flits are duck-typed: anything with ``opcode``, ``srcid``, ``txnid``,
``resp``, ``resperr``, ``dbid``, ``pcrdtype``, ``homenid``, ``dataid``,
``data`` and ``be`` attributes (missing ones read as 0), so the unit tests
run on ``SimpleNamespace`` and the BFM on :class:`CHIRspFlit` /
:class:`CHIDatFlit`.

Scope: the request set of this release only (reads, dataless, immediate
and CopyBack writes, PCrdReturn); no DWT, no stash, no atomics, no DVM, no
WriteDataCancel, ReadReceipt accepted when Order != 0 and nothing more.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .chi_opcodes import DatOpcode, ReqOpcode, RspOpcode, Size, data_id, data_ids_for, resp_state

MAX_TXNID = 1 << 12          # B2.4.2: 12-bit TxnID
MAX_OUTSTANDING = 1024       # B2.4.2 / B2.10: at most 1024 outstanding per Requester
MAX_PCRDTYPE = 16            # B2.10: up to 16 credit types
LINE_BYTES = 64


class ReqClass(Enum):
    READ_ALLOC = 'read_alloc'          # B2.3.1.1
    READ_NOALLOC = 'read_noalloc'      # B2.3.1.2
    DATALESS = 'dataless'              # B2.3.5 alt 1 (Comp only)
    DATALESS_ACK = 'dataless_ack'      # B2.3.5 alt 2 (Comp then CompAck)
    WRITE_IMM = 'write_imm'            # B2.3.2.1
    WRITE_COPYBACK = 'write_copyback'  # B2.3.2.3
    PCRD_RETURN = 'pcrd_return'        # B2.10.1: no response at all


REQ_CLASS: Dict[ReqOpcode, ReqClass] = {
    ReqOpcode.ReadNoSnp: ReqClass.READ_NOALLOC,
    ReqOpcode.ReadOnce: ReqClass.READ_NOALLOC,
    ReqOpcode.ReadOnceCleanInvalid: ReqClass.READ_NOALLOC,
    ReqOpcode.ReadOnceMakeInvalid: ReqClass.READ_NOALLOC,
    ReqOpcode.ReadClean: ReqClass.READ_ALLOC,
    ReqOpcode.ReadNotSharedDirty: ReqClass.READ_ALLOC,
    ReqOpcode.ReadShared: ReqClass.READ_ALLOC,
    ReqOpcode.ReadUnique: ReqClass.READ_ALLOC,
    ReqOpcode.ReadPreferUnique: ReqClass.READ_ALLOC,
    ReqOpcode.MakeReadUnique: ReqClass.READ_ALLOC,
    ReqOpcode.Evict: ReqClass.DATALESS,
    ReqOpcode.CleanShared: ReqClass.DATALESS,
    ReqOpcode.CleanInvalid: ReqClass.DATALESS,
    ReqOpcode.MakeInvalid: ReqClass.DATALESS,
    ReqOpcode.CleanUnique: ReqClass.DATALESS_ACK,
    ReqOpcode.MakeUnique: ReqClass.DATALESS_ACK,
    ReqOpcode.WriteNoSnpPtl: ReqClass.WRITE_IMM,
    ReqOpcode.WriteNoSnpFull: ReqClass.WRITE_IMM,
    ReqOpcode.WriteUniquePtl: ReqClass.WRITE_IMM,
    ReqOpcode.WriteUniqueFull: ReqClass.WRITE_IMM,
    ReqOpcode.WriteBackFull: ReqClass.WRITE_COPYBACK,
    ReqOpcode.WriteBackPtl: ReqClass.WRITE_COPYBACK,
    ReqOpcode.WriteCleanFull: ReqClass.WRITE_COPYBACK,
    ReqOpcode.WriteEvictFull: ReqClass.WRITE_COPYBACK,
    ReqOpcode.WriteEvictOrEvict: ReqClass.WRITE_COPYBACK,
    ReqOpcode.PCrdReturn: ReqClass.PCRD_RETURN,
}

# B2.3.1.1 alt 6 / Table B4.39: the only read that may complete with a bare Comp
_COMP_ONLY_READS = (ReqOpcode.MakeReadUnique,)
# B2.3.2.3 alt 1a: Comp without data is for WriteEvictOrEvict, or CAH = 1
_COPYBACK_COMP_BY_OPCODE = (ReqOpcode.WriteEvictOrEvict,)


def req_class(opcode) -> ReqClass:
    cls = REQ_CLASS.get(ReqOpcode(opcode))
    if cls is None:
        raise ValueError(f"{ReqOpcode(opcode).name} is outside this release's request set")
    return cls


def needs_compack(opcode, expcompack: int) -> bool:
    """Table B2.8 for an RN-F: Y for allocating reads, CleanUnique and
    MakeUnique (ExpCompAck must be 1); O for ReadNoSnp / ReadOnce* and
    WriteNoSnp / WriteUnique (follow ExpCompAck); N for CMO / Evict; H for
    CopyBack (decided when Home answers, so False here)."""
    cls = req_class(opcode)
    if cls in (ReqClass.READ_ALLOC, ReqClass.DATALESS_ACK):
        return True
    if cls in (ReqClass.READ_NOALLOC, ReqClass.WRITE_IMM):
        return bool(expcompack)
    return False


def write_data_opcode(opcode) -> DatOpcode:
    """Table B4.44: CopyBackWriteData for CopyBack writes, NonCopyBackWriteData
    for Immediate writes."""
    cls = req_class(opcode)
    if cls == ReqClass.WRITE_COPYBACK:
        return DatOpcode.CopyBackWriteData
    if cls == ReqClass.WRITE_IMM:
        return DatOpcode.NonCopyBackWriteData
    raise ValueError(f"{ReqOpcode(opcode).name} carries no write data")


class Action:
    """Something the BFM must do, with keyword parameters readable as
    attributes. Kinds: ``send_compack`` (tgtid, txnid), ``send_write_data``
    (tgtid, txnid, opcode, state), ``retry`` (pcrdtype), ``done``, ``error``
    (text)."""
    KINDS = ('send_compack', 'send_write_data', 'retry', 'done', 'error')

    def __init__(self, kind: str, **params):
        if kind not in self.KINDS:
            raise ValueError(f"unknown Action kind {kind!r}")
        self.kind = kind
        self.params = dict(params)

    def __getattr__(self, name):
        params = self.__dict__.get('params', {})
        if name in params:
            return params[name]
        raise AttributeError(name)

    def __eq__(self, other):
        return isinstance(other, Action) and other.kind == self.kind and other.params == self.params

    def __repr__(self):
        inner = ', '.join(f"{k}={v!r}" for k, v in self.params.items())
        return f"Action({self.kind}{', ' + inner if inner else ''})"


def _f(flit, name, default=0):
    """Field read that tolerates an absent field (duck-typed flits)."""
    try:
        v = getattr(flit, name)
    except (AttributeError, KeyError):
        return default
    return default if v is None else v


def _bus_width(flit, fallback: Optional[int]) -> int:
    cfg = _f(flit, 'cfg', None)
    width = getattr(cfg, 'data_width', None) if cfg is not None else None
    if width is None:
        width = fallback
    if width not in (128, 256, 512):
        raise ValueError("data bus width unknown: set CHITransaction.data_width or pass flits with a cfg (B2.9.4)")
    return width


@dataclass
class CHITransaction:
    """One request and its progress. Field names match the REQ flit."""
    opcode: ReqOpcode
    addr: int
    size: Size = Size.B64
    txnid: Optional[int] = None
    srcid: int = 0
    tgtid: int = 0
    expcompack: int = 0
    order: int = 0
    memattr: int = 0
    snpattr: int = 0
    likelyshared: int = 0
    excl: int = 0
    lpid: int = 0
    qos: int = 0
    allowretry: int = 1
    pcrdtype: int = 0
    cah: int = 0
    data: Optional[bytes] = None      # write payload: nbytes over the size-aligned window
    be: Optional[int] = None          # byte enables over that window (None = all)
    data_width: Optional[int] = None  # bus width when the flits carry no cfg
    # runtime
    status: str = 'issued'
    received: List[Tuple[str, object]] = field(default_factory=list)
    dbid: Optional[int] = None
    dbid_src: Optional[int] = None
    comp_seen: bool = False
    dbid_seen: bool = False
    respsep_seen: bool = False
    readreceipt_seen: bool = False
    data_chunks: Dict[int, Tuple[int, int, int]] = field(default_factory=dict)
    comp_state: Optional[str] = None
    resperr: int = 0
    retry_pcrdtype: Optional[int] = None
    compack_sent: bool = False
    compack_tgt: Optional[int] = None
    data_sent: bool = False
    stats: Dict[str, int] = field(default_factory=dict)
    expected_ids: Optional[List[int]] = field(default=None, repr=False)   # DataIDs owed, set on first chunk
    data_op: Optional[DatOpcode] = field(default=None, repr=False)        # CompData or DataSepResp
    bus_width: Optional[int] = field(default=None, repr=False)            # width seen on the first chunk

    def __post_init__(self):
        self.opcode = ReqOpcode(self.opcode)
        self.size = Size(self.size)
        if self.cls == ReqClass.PCRD_RETURN:
            # B2.10.1: a No-Op that spends a pre-allocated credit, so AllowRetry
            # is 0 (B2.10.2.1) and Addr is unused and must be 0 (B13.10.20)
            self.status = 'done'
            self.allowretry = 0
            self.addr = 0

    # -- derived ------------------------------------------------------------
    @property
    def cls(self) -> ReqClass:
        return req_class(self.opcode)

    @property
    def is_write(self) -> bool:
        return self.cls in (ReqClass.WRITE_IMM, ReqClass.WRITE_COPYBACK)

    @property
    def is_read(self) -> bool:
        return self.cls in (ReqClass.READ_ALLOC, ReqClass.READ_NOALLOC)

    @property
    def nbytes(self) -> int:
        return self.size.nbytes

    @property
    def window(self) -> int:
        """Start of the size-aligned window the transfer covers (B2.9.4)."""
        return (self.addr // self.nbytes) * self.nbytes

    @property
    def needs_compack(self) -> bool:
        return needs_compack(self.opcode, self.expcompack)

    def data_ids(self, data_width: int) -> List[int]:
        """DataIDs of the packets this transfer needs (B2.9.4 Table B2.16)."""
        return data_ids_for(self.nbytes, self.addr, data_width)

    def validate(self) -> List[str]:
        """Static checks a request must pass before issue."""
        problems = []
        if self.cls in (ReqClass.READ_ALLOC, ReqClass.DATALESS_ACK) and not self.expcompack:
            problems.append(f"{self.opcode.name} requires ExpCompAck = 1 (Table B2.8)")
        if self.cls in (ReqClass.DATALESS, ReqClass.PCRD_RETURN) and self.expcompack:
            problems.append(f"{self.opcode.name} must not use CompAck (Table B2.8)")
        if self.cls == ReqClass.WRITE_COPYBACK and self.expcompack:
            problems.append("CopyBack writes must not set ExpCompAck; CompAck follows Comp regardless (B2.7.3)")
        if self.allowretry and self.pcrdtype:
            problems.append("PCrdType must be 0 when AllowRetry is 1 (B2.10.2.2)")
        if self.is_write and self.data is not None and len(self.data) != self.nbytes:
            problems.append(f"write payload is {len(self.data)} bytes, Size says {self.nbytes}")
        if self.txnid is not None and not 0 <= self.txnid < MAX_TXNID:
            problems.append(f"TxnID {self.txnid} does not fit 12 bits (B2.4.2)")
        return problems

    # -- bookkeeping --------------------------------------------------------
    def _count(self, key: str):
        self.stats[key] = self.stats.get(key, 0) + 1

    def _record(self, channel: str, flit, opcode_name: str):
        self.received.append((channel, flit))
        self._count(opcode_name)
        err = int(_f(flit, 'resperr'))
        if err:
            self.resperr = err
            self._count('resperr')

    def _error(self, text: str) -> List[Action]:
        self._count('errors')
        return [Action('error', text=f"{self.opcode.name} txn {self.txnid}: {text}")]

    def _finish(self) -> List[Action]:
        if self.status != 'done' and self.complete():
            self.status = 'done'
            return [Action('done')]
        return []

    def _compack(self, tgtid: int, txnid: int) -> List[Action]:
        self.compack_sent = True
        self.compack_tgt = tgtid
        return [Action('send_compack', tgtid=tgtid, txnid=txnid)]

    def _write_data(self, tgtid: int, txnid: int, state: Optional[str] = None) -> List[Action]:
        self.data_sent = True
        return [Action('send_write_data', tgtid=tgtid, txnid=txnid,
                       opcode=write_data_opcode(self.opcode), state=state)]

    def prepare_resend(self, pcrdtype: int):
        """B2.10: the second attempt keeps every field except AllowRetry = 0
        and PCrdType = the RetryAck's type."""
        self.allowretry = 0
        self.pcrdtype = int(pcrdtype)
        self.status = 'retried'
        self._count('retries')

    def complete(self) -> bool:
        cls = self.cls
        if cls == ReqClass.PCRD_RETURN:
            return True
        if self.status in ('retry_wait', 'cancelled'):
            return False
        if cls in (ReqClass.READ_ALLOC, ReqClass.READ_NOALLOC):
            if self.readreceipt_pending():
                return False
            if self.comp_seen and self.opcode in _COMP_ONLY_READS and not self.data_chunks:
                return self.compack_sent or not self.needs_compack
            have_resp = self.comp_seen or self.respsep_seen
            return have_resp and self._all_data_in() and (self.compack_sent or not self.needs_compack)
        if cls == ReqClass.DATALESS:
            return self.comp_seen
        if cls == ReqClass.DATALESS_ACK:
            return self.comp_seen and self.compack_sent
        if cls == ReqClass.WRITE_IMM:
            return self.comp_seen and self.data_sent and (self.compack_sent or not self.expcompack)
        if cls == ReqClass.WRITE_COPYBACK:
            return self.data_sent or (self.comp_seen and self.compack_sent)
        return False

    def readreceipt_pending(self) -> bool:
        return self.is_read and self.order != 0 and not self.readreceipt_seen

    def _all_data_in(self) -> bool:
        return self.expected_ids is not None and set(self.data_chunks) == set(self.expected_ids)

    # -- RSP channel --------------------------------------------------------
    def on_rsp(self, flit) -> List[Action]:
        """Consume a RSP flit addressed to this TxnID."""
        op = RspOpcode(int(_f(flit, 'opcode')))
        self._record('rsp', flit, op.name)
        if op == RspOpcode.RetryAck:
            return self._on_retry_ack(flit)
        if self.status == 'retry_wait':
            return self._error(f"{op.name} while waiting for PCrdGrant after RetryAck (B2.10)")
        if op == RspOpcode.PCrdGrant:
            return self._error("PCrdGrant carries no TxnID; route it through RequesterTracker (B2.10)")
        if op == RspOpcode.CompAck:
            return self._error("CompAck is a Requester-to-Completer response, never received by a Requester")
        cls = self.cls
        if cls == ReqClass.PCRD_RETURN:
            return self._error(f"{op.name} for a PCrdReturn, which has no response (B2.10.1)")
        dup = self._duplicate(op)
        if dup:
            return self._error(dup)
        if self.status == 'done':
            return self._error(f"{op.name} after the transaction completed")
        if cls in (ReqClass.READ_ALLOC, ReqClass.READ_NOALLOC):
            return self._read_rsp(op, flit)
        if cls in (ReqClass.DATALESS, ReqClass.DATALESS_ACK):
            return self._dataless_rsp(op, flit)
        if cls == ReqClass.WRITE_IMM:
            return self._write_imm_rsp(op, flit)
        return self._copyback_rsp(op, flit)

    def _duplicate(self, op: RspOpcode) -> Optional[str]:
        """A completion seen twice, named before the generic 'already done'."""
        if op == RspOpcode.Comp and self.comp_seen:
            if self.cls == ReqClass.WRITE_COPYBACK and self.dbid_seen:
                return "Comp after CompDBIDResp for a CopyBack"
            return "Comp twice"
        if op in (RspOpcode.DBIDResp, RspOpcode.DBIDRespOrd) and self.dbid_seen and self.cls == ReqClass.WRITE_IMM:
            return "DBIDResp twice"
        if op == RspOpcode.CompDBIDResp and self.comp_seen and self.dbid_seen:
            return "CompDBIDResp twice"
        if op == RspOpcode.RespSepData and self.respsep_seen:
            return "RespSepData twice"
        return None

    def _on_retry_ack(self, flit) -> List[Action]:
        if self.comp_seen or self.dbid_seen or self.respsep_seen or self.data_chunks or self.readreceipt_seen:
            return self._error("RetryAck after another response was accepted (B2.10: a request is either accepted or retried)")
        if not self.allowretry:
            return self._error("RetryAck for a request sent with AllowRetry = 0 (B2.10: guaranteed to be accepted)")
        self.status = 'retry_wait'
        self.retry_pcrdtype = int(_f(flit, 'pcrdtype'))
        return [Action('retry', pcrdtype=self.retry_pcrdtype)]

    def _read_rsp(self, op: RspOpcode, flit) -> List[Action]:
        if op == RspOpcode.ReadReceipt:
            if self.order == 0:
                return self._error("ReadReceipt for a read with Order = 0 (B2.3.1: ReadReceipt only when Order != 0)")
            if self.readreceipt_seen:
                return self._error("ReadReceipt twice")
            self.readreceipt_seen = True
            return self._finish()
        if op == RspOpcode.RespSepData:
            if self.respsep_seen:
                return self._error("RespSepData twice")
            if self.comp_seen:
                return self._error("RespSepData after CompData / Comp (B2.3.1: one completion alternative per transaction)")
            self.respsep_seen = True
            self.dbid = int(_f(flit, 'dbid'))
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            acts = []
            # B2.7.4: CompAck after RespSepData, may precede DataSepResp, except
            # ordered ReadNoSnp / ReadOnce which must wait for both
            if self.needs_compack and not self.compack_sent and not (self.cls == ReqClass.READ_NOALLOC and self.order):
                acts += self._compack(int(_f(flit, 'srcid')), self.dbid)
            return acts + self._finish()
        if op == RspOpcode.Comp:
            if self.opcode not in _COMP_ONLY_READS:
                return self._error("Comp for a read (only MakeReadUnique may complete with Comp, B2.3.1 alt 6)")
            if self.comp_seen or self.respsep_seen or self.data_chunks:
                return self._error("Comp after a data response for MakeReadUnique")
            self.comp_seen = True
            self.dbid = int(_f(flit, 'dbid'))
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            return self._compack(int(_f(flit, 'srcid')), self.dbid) + self._finish()
        if op in (RspOpcode.DBIDResp, RspOpcode.DBIDRespOrd, RspOpcode.CompDBIDResp):
            return self._error(f"{op.name} for a read (no write data is owed)")
        return self._error(f"{op.name} is not a legal response to a read")

    def _dataless_rsp(self, op: RspOpcode, flit) -> List[Action]:
        if op != RspOpcode.Comp:
            return self._error(f"{op.name} for a Dataless request (B2.3.5: Comp only)")
        if self.comp_seen:
            return self._error("Comp twice")
        self.comp_seen = True
        self.dbid = int(_f(flit, 'dbid'))
        self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
        acts = []
        if self.cls == ReqClass.DATALESS_ACK:
            acts += self._compack(int(_f(flit, 'srcid')), self.dbid)
        return acts + self._finish()

    def _write_imm_rsp(self, op: RspOpcode, flit) -> List[Action]:
        src = int(_f(flit, 'srcid'))
        dbid = int(_f(flit, 'dbid'))
        if op in (RspOpcode.DBIDResp, RspOpcode.DBIDRespOrd):
            if self.dbid_seen:
                return self._error("DBIDResp twice")
            if self.comp_seen and self.dbid_src == src and self.dbid != dbid:
                return self._error(f"DBID {dbid} in DBIDResp differs from {self.dbid} in Comp from the same source (B2.4.3)")
            self.dbid_seen, self.dbid, self.dbid_src = True, dbid, src
            return self._write_data(src, dbid) + self._finish()
        if op == RspOpcode.Comp:
            if self.comp_seen:
                return self._error("Comp twice")
            if self.dbid_seen and self.dbid_src == src and self.dbid != dbid:
                return self._error(f"DBID {dbid} in Comp differs from {self.dbid} in DBIDResp from the same source (B2.4.3)")
            self.comp_seen = True
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            if not self.dbid_seen:
                self.dbid, self.dbid_src = dbid, src
            acts = []
            if self.expcompack:
                acts += self._compack(src, self.dbid)
            return acts + self._finish()
        if op == RspOpcode.CompDBIDResp:
            if self.dbid_seen or self.comp_seen:
                return self._error("CompDBIDResp after a separate DBIDResp / Comp (B2.3.2.1: alt 2a1 or 2a2, not both)")
            self.dbid_seen = self.comp_seen = True
            self.dbid, self.dbid_src = dbid, src
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            acts = self._write_data(src, dbid)
            if self.expcompack:
                acts += self._compack(src, dbid)
            return acts + self._finish()
        return self._error(f"{op.name} is not a legal response to an Immediate Write")

    def _copyback_rsp(self, op: RspOpcode, flit) -> List[Action]:
        src = int(_f(flit, 'srcid'))
        dbid = int(_f(flit, 'dbid'))
        if op == RspOpcode.CompDBIDResp:
            if self.comp_seen or self.dbid_seen:
                return self._error("CompDBIDResp twice")
            self.dbid_seen = self.comp_seen = True
            self.dbid, self.dbid_src = dbid, src
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            return self._write_data(src, dbid) + self._finish()
        if op == RspOpcode.Comp:
            if self.opcode not in _COPYBACK_COMP_BY_OPCODE and not self.cah:
                return self._error("Comp without DBID for a CopyBack that is not WriteEvictOrEvict and has CAH = 0 "
                                   "(B2.3.2.3 alt 2: CompDBIDResp is the only completion)")
            if self.comp_seen or self.dbid_seen:
                return self._error("Comp after CompDBIDResp / Comp for a CopyBack")
            self.comp_seen = True
            self.dbid = dbid
            self.comp_state = resp_state('comp', int(_f(flit, 'resp')))
            return self._compack(src, dbid) + self._finish()
        if op in (RspOpcode.DBIDResp, RspOpcode.DBIDRespOrd):
            return self._error(f"{op.name} for a CopyBack (B2.3.2.3: CompDBIDResp or Comp)")
        return self._error(f"{op.name} is not a legal response to a CopyBack write")

    # -- DAT channel --------------------------------------------------------
    def on_dat(self, flit) -> List[Action]:
        """Consume a DAT flit addressed to this TxnID."""
        op = DatOpcode(int(_f(flit, 'opcode')))
        self._record('dat', flit, op.name)
        if self.status == 'retry_wait':
            return self._error(f"{op.name} while waiting for PCrdGrant after RetryAck (B2.10)")
        if self.status == 'done':
            return self._error(f"{op.name} after the transaction completed")
        if not self.is_read:
            return self._error(f"{op.name} on DAT for a {self.cls.value} request, which receives no data")
        if op not in (DatOpcode.CompData, DatOpcode.DataSepResp):
            return self._error(f"{op.name} is not a read data response (CompData or DataSepResp)")
        if op == DatOpcode.CompData and self.respsep_seen:
            return self._error("CompData after RespSepData (B2.3.1: separate response needs DataSepResp)")
        if op == DatOpcode.DataSepResp and self.comp_seen:
            return self._error("DataSepResp after CompData / Comp")
        if self.data_chunks and self.data_op != op:
            return self._error(f"{op.name} mixed with {self.data_op.name} in one data response (B2.9.4)")
        width = _bus_width(flit, self.data_width)
        if self.expected_ids is None:
            self.expected_ids = self.data_ids(width)
            self.bus_width = width
        did = int(_f(flit, 'dataid'))
        if did not in self.expected_ids:
            return self._error(f"DataID {did} is not one of {self.expected_ids} for {self.nbytes} B at "
                               f"{self.addr:#x} on a {width}-bit bus (B2.9.4)")
        if did in self.data_chunks:
            return self._error(f"DataID {did} twice")
        state = resp_state('comp', int(_f(flit, 'resp')))
        if self.comp_state is not None and state != self.comp_state and op == DatOpcode.CompData:
            return self._error(f"Resp {state} differs from {self.comp_state} in an earlier packet (B2.9.4)")
        self.data_op = op
        self.data_chunks[did] = (int(_f(flit, 'data')), int(_f(flit, 'be', -1)), int(_f(flit, 'resp')))
        self.comp_state = state
        acts = []
        if op == DatOpcode.CompData:
            if not self.comp_seen:
                self.comp_seen = True
                self.dbid = int(_f(flit, 'dbid'))
            if self._all_data_in() and self.needs_compack and not self.compack_sent:
                acts += self._compack(int(_f(flit, 'homenid')), self.dbid)
        elif self.respsep_seen and self._all_data_in() and self.needs_compack and not self.compack_sent:
            acts += self._compack(int(_f(flit, 'homenid')), self.dbid)
        return acts + self._finish()

    def read_data(self) -> Optional[bytes]:
        """The ``nbytes`` of the window, assembled from the chunks at their
        natural byte positions (B2.9.4), once every chunk is in."""
        if not self._all_data_in():
            return None
        step = self.bus_width // 8
        line = bytearray(LINE_BYTES)
        for did, (data, _be, _resp) in self.data_chunks.items():
            off = _chunk_offset(did, self.bus_width)
            line[off:off + step] = int(data).to_bytes(step, 'little')
        lo = self.window % LINE_BYTES
        return bytes(line[lo:lo + self.nbytes])

    def write_chunks(self, data_width: int) -> List[Tuple[int, int, int]]:
        """(dataid, data, be) per packet for the write payload, bytes at
        natural positions (B2.9.4). ``be`` bits are packet-relative."""
        if self.data is None:
            raise ValueError("no write payload")
        step = data_width // 8
        lo = self.window
        line_base = lo - lo % LINE_BYTES
        mask = (1 << self.nbytes) - 1 if self.be is None else int(self.be)
        out = []
        for did in self.data_ids(data_width):
            pkt = bytearray(step)
            be = 0
            base = line_base + _chunk_offset(did, data_width)
            for i in range(step):
                j = base + i - lo
                if 0 <= j < self.nbytes and mask >> j & 1:
                    pkt[i] = self.data[j]
                    be |= 1 << i
            out.append((did, int.from_bytes(pkt, 'little'), be))
        return out


def _chunk_offset(dataid: int, data_width: int) -> int:
    """Byte offset within the 64-byte line of packet ``dataid`` (Table B2.16)."""
    if data_width == 128:
        return dataid * 16
    if data_width == 256:
        return (dataid >> 1) * 32
    return 0


# ---------------------------------------------------------------------------
# Requester side
# ---------------------------------------------------------------------------
class TxnIdPool:
    """TxnID allocator (B2.4.2: 12 bits, at most 1024 outstanding)."""

    def __init__(self, max_outstanding: int = MAX_OUTSTANDING):
        if not 1 <= max_outstanding <= MAX_OUTSTANDING:
            raise ValueError(f"max_outstanding must be 1..{MAX_OUTSTANDING} (B2.4.2)")
        self.max_outstanding = max_outstanding
        self._in_use = set()
        self._next = 0

    def allocate(self) -> int:
        if len(self._in_use) >= self.max_outstanding:
            raise RuntimeError(f"TxnID pool exhausted: {self.max_outstanding} outstanding (B2.4.2)")
        for _ in range(MAX_TXNID):
            cand = self._next
            self._next = (self._next + 1) % MAX_TXNID
            if cand not in self._in_use:
                self._in_use.add(cand)
                return cand
        raise RuntimeError("TxnID pool exhausted")

    def free(self, txnid: int):
        self._in_use.discard(int(txnid))

    def reserve(self, txnid: int):
        if txnid in self._in_use:
            raise ValueError(f"TxnID {txnid} already in use (B2.4.2: unique per Requester)")
        if len(self._in_use) >= self.max_outstanding:
            raise RuntimeError(f"TxnID pool exhausted: {self.max_outstanding} outstanding (B2.4.2)")
        self._in_use.add(int(txnid))

    @property
    def outstanding(self) -> int:
        return len(self._in_use)

    def in_use(self, txnid: int) -> bool:
        return int(txnid) in self._in_use


class RequesterTracker:
    """All in-flight transactions of one Requester, keyed by TxnID; the retry
    machinery of B2.10 (RetryAck, PCrdGrant, banked credits, re-send)."""

    def __init__(self, srcid: int, pool: Optional[TxnIdPool] = None):
        self.srcid = srcid
        self.pool = pool or TxnIdPool()
        self.txns: Dict[int, CHITransaction] = {}
        self.credits_banked: Dict[int, int] = {}
        self.waiting: Dict[int, List[CHITransaction]] = {}
        self.retired_count = 0

    def issue(self, txn: CHITransaction) -> CHITransaction:
        """Register ``txn`` (allocating a TxnID when it has none). A re-issue
        after a retry is a no-op: the entry is already there."""
        if txn.txnid is not None and self.txns.get(txn.txnid) is txn:
            return txn
        txn.srcid = self.srcid
        problems = txn.validate()
        if problems:
            raise ValueError('; '.join(problems))
        if txn.txnid is None:
            txn.txnid = self.pool.allocate()
        else:
            self.pool.reserve(txn.txnid)
        if txn.cls == ReqClass.PCRD_RETURN:
            self._take_credit(txn.pcrdtype)
            self.pool.free(txn.txnid)
            txn.status = 'done'
            return txn
        self.txns[txn.txnid] = txn
        return txn

    def _take_credit(self, pcrdtype: int):
        n = self.credits_banked.get(pcrdtype, 0)
        if n <= 0:
            raise ValueError(f"no banked P-Credit of type {pcrdtype} to return (B2.10.1)")
        self.credits_banked[pcrdtype] = n - 1

    def _lookup(self, flit, channel: str) -> Tuple[Optional[CHITransaction], List[Action]]:
        txnid = int(_f(flit, 'txnid'))
        txn = self.txns.get(txnid)
        if txn is None:
            return None, [Action('error', text=f"{channel.upper()} flit for unknown TxnID {txnid} at RN {self.srcid}")]
        return txn, []

    def route_rsp(self, flit) -> Tuple[Optional[CHITransaction], List[Action]]:
        op = RspOpcode(int(_f(flit, 'opcode')))
        if op == RspOpcode.PCrdGrant:
            txn = self.grant(int(_f(flit, 'pcrdtype')))
            return (txn, [Action('retry', pcrdtype=txn.pcrdtype)]) if txn is not None else (None, [])
        txn, errs = self._lookup(flit, 'rsp')
        if txn is None:
            return None, errs
        actions = txn.on_rsp(flit)
        if op == RspOpcode.RetryAck and txn.status == 'retry_wait':
            ready = self.on_retry_ack(txn, txn.retry_pcrdtype)
            actions = [a for a in actions if a.kind != 'retry']
            if ready:
                actions.append(Action('retry', pcrdtype=txn.pcrdtype))
        return self._after(txn, actions)

    def route_dat(self, flit) -> Tuple[Optional[CHITransaction], List[Action]]:
        txn, errs = self._lookup(flit, 'dat')
        if txn is None:
            return None, errs
        return self._after(txn, txn.on_dat(flit))

    def _after(self, txn, actions):
        if txn.status == 'done':
            self.retired(txn)
        return txn, actions

    def on_retry_ack(self, txn: CHITransaction, pcrdtype: int) -> bool:
        """Credit in hand -> prepare the re-send now (True); else queue."""
        if self.credits_banked.get(pcrdtype, 0) > 0:
            self.credits_banked[pcrdtype] -= 1
            txn.prepare_resend(pcrdtype)
            return True
        self.waiting.setdefault(pcrdtype, []).append(txn)
        return False

    def grant(self, pcrdtype: int) -> Optional[CHITransaction]:
        """PCrdGrant: bank the credit; if a transaction waits for that type,
        hand it the credit (B2.10: no fixed credit-to-transaction binding;
        oldest waiter first)."""
        queue = self.waiting.get(pcrdtype)
        if queue:
            txn = queue.pop(0)
            txn.prepare_resend(pcrdtype)
            return txn
        self.credits_banked[pcrdtype] = self.credits_banked.get(pcrdtype, 0) + 1
        return None

    def cancel(self, txn: CHITransaction):
        """Drop a transaction that is waiting for a credit (B2.10.1 scenario 1).
        The credit, when it arrives, is banked and must go back by PCrdReturn."""
        for queue in self.waiting.values():
            if txn in queue:
                queue.remove(txn)
        txn.status = 'cancelled'
        self.retired(txn)

    def retired(self, txn: CHITransaction):
        if self.txns.get(txn.txnid) is txn:
            del self.txns[txn.txnid]
            self.pool.free(txn.txnid)
            self.retired_count += 1

    @property
    def outstanding(self) -> int:
        return len(self.txns)


# ---------------------------------------------------------------------------
# Completer side
# ---------------------------------------------------------------------------
@dataclass
class CompleterEntry:
    srcid: int
    txnid: int
    opcode: ReqOpcode
    addr: int
    size: Size
    expcompack: int = 0
    order: int = 0
    allowretry: int = 1
    pcrdtype: int = 0
    cah: int = 0
    dbid: Optional[int] = None
    data_chunks: Dict[int, Tuple[int, int, int]] = field(default_factory=dict)
    expected_ids: Optional[List[int]] = None
    write_complete: bool = False
    compack_seen: bool = False
    comp_sent: bool = False
    dbid_sent: bool = False
    data_sent: bool = False
    writedata_state: Optional[str] = None
    compack_state: Optional[str] = None

    @property
    def cls(self) -> ReqClass:
        return req_class(self.opcode)

    @property
    def nbytes(self) -> int:
        return self.size.nbytes

    @property
    def key(self):
        return (self.srcid, self.txnid)


class CompleterTracker:
    """Home-side bookkeeping: requests in flight keyed by (SrcID, TxnID),
    DBID allocation, and the rendezvous of WriteData / CompAck (TxnID ==
    DBID) back to the request (B2.4.3). DBIDs are unique across all
    Requesters here, which satisfies the per-Requester rule."""

    def __init__(self, max_dbid: int = MAX_OUTSTANDING, data_width: Optional[int] = None):
        self.entries: Dict[Tuple[int, int], CompleterEntry] = {}
        self.dbids: Dict[Tuple[int, int], CompleterEntry] = {}
        self.pool = TxnIdPool(max_dbid)
        self.data_width = data_width

    def accept(self, req_flit) -> CompleterEntry:
        opcode = ReqOpcode(int(_f(req_flit, 'opcode')))
        entry = CompleterEntry(
            srcid=int(_f(req_flit, 'srcid')), txnid=int(_f(req_flit, 'txnid')), opcode=opcode,
            addr=int(_f(req_flit, 'addr')), size=Size(int(_f(req_flit, 'size'))),
            expcompack=int(_f(req_flit, 'expcompack')), order=int(_f(req_flit, 'order')),
            allowretry=int(_f(req_flit, 'allowretry')), pcrdtype=int(_f(req_flit, 'pcrdtype')),
            cah=int(_f(req_flit, 'cah')))
        if entry.key in self.entries:
            raise ValueError(f"TxnID {entry.txnid} from RN {entry.srcid} is already in flight (B2.4.2)")
        if entry.allowretry and entry.pcrdtype:
            raise ValueError("PCrdType must be 0 when AllowRetry is 1 (B2.10.2.2)")
        self.entries[entry.key] = entry
        return entry

    def allocate_dbid(self, entry: CompleterEntry) -> int:
        if entry.dbid is not None:
            return entry.dbid
        entry.dbid = self.pool.allocate()
        self.dbids[(entry.srcid, entry.dbid)] = entry
        return entry.dbid

    def by_dbid(self, srcid: int, dbid: int) -> Optional[CompleterEntry]:
        return self.dbids.get((int(srcid), int(dbid)))

    def by_txnid(self, srcid: int, txnid: int) -> Optional[CompleterEntry]:
        return self.entries.get((int(srcid), int(txnid)))

    def expected_data_ids(self, entry: CompleterEntry, data_width: int) -> List[int]:
        return data_ids_for(entry.nbytes, entry.addr, data_width)

    def _rendezvous(self, flit, what: str) -> CompleterEntry:
        src, txnid = int(_f(flit, 'srcid')), int(_f(flit, 'txnid'))
        entry = self.by_dbid(src, txnid)
        if entry is None:
            raise LookupError(f"{what} from RN {src} with TxnID {txnid} matches no DBID handed to that RN (B2.4.3)")
        return entry

    def on_write_data(self, flit) -> CompleterEntry:
        op = DatOpcode(int(_f(flit, 'opcode')))
        entry = self._rendezvous(flit, op.name)
        want = write_data_opcode(entry.opcode)
        if op == DatOpcode.NonCopyBackWriteDataCompAck:
            if want != DatOpcode.NonCopyBackWriteData:
                raise ValueError(f"{op.name} for a {entry.opcode.name} (CopyBack data cannot carry CompAck)")
            entry.compack_seen = True
        elif op != want:
            raise ValueError(f"{op.name} for a {entry.opcode.name}; Table B4.44 wants {want.name}")
        width = _bus_width(flit, self.data_width)
        if entry.expected_ids is None:
            entry.expected_ids = self.expected_data_ids(entry, width)
        did = int(_f(flit, 'dataid'))
        if did not in entry.expected_ids:
            raise ValueError(f"DataID {did} is not one of {entry.expected_ids} for {entry.opcode.name} "
                             f"{entry.nbytes} B at {entry.addr:#x} (B2.9.4)")
        if did in entry.data_chunks:
            raise ValueError(f"DataID {did} twice from RN {entry.srcid}")
        entry.data_chunks[did] = (int(_f(flit, 'data')), int(_f(flit, 'be', -1)), int(_f(flit, 'resp')))
        entry.writedata_state = resp_state('writedata', int(_f(flit, 'resp')))
        entry.write_complete = set(entry.data_chunks) == set(entry.expected_ids)
        return entry

    def on_compack(self, flit) -> CompleterEntry:
        entry = self._rendezvous(flit, 'CompAck')
        if entry.compack_seen:
            raise ValueError(f"CompAck twice for RN {entry.srcid} TxnID {entry.txnid}")
        entry.compack_seen = True
        entry.compack_state = resp_state('compack', int(_f(flit, 'resp')))
        return entry

    def retire(self, entry: CompleterEntry):
        self.entries.pop(entry.key, None)
        if entry.dbid is not None:
            self.dbids.pop((entry.srcid, entry.dbid), None)
            self.pool.free(entry.dbid)

    @property
    def outstanding(self) -> int:
        return len(self.entries)


__all__ = [
    'ReqClass', 'REQ_CLASS', 'req_class', 'needs_compack', 'write_data_opcode', 'Action',
    'CHITransaction', 'TxnIdPool', 'RequesterTracker', 'CompleterEntry', 'CompleterTracker',
    'MAX_TXNID', 'MAX_OUTSTANDING', 'MAX_PCRDTYPE', 'data_id',
]
