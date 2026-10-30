# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_rn
# Purpose: CHI Request Node BFM (RN-F / RN-I): issues requests, completes
#          them, answers snoops from a cache model
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI Request Node BFM.

Drives the RN side of a port (the DUT is the interconnect / Home side).
A test calls :meth:`read`, :meth:`write` or :meth:`dataless` and awaits
the returned :class:`CHITransaction`, or :meth:`issue` to fire and forget
and :meth:`wait` later. The BFM:

* allocates TxnIDs (B2.4.2), sends the REQ flit, routes every RSP/DAT
  flit back to its transaction with :class:`RequesterTracker`, and acts
  on what the transaction says (B2.3): CompAck after Comp / CompData /
  RespSepData when the request expects one (B2.7.3), write data after
  DBIDResp / CompDBIDResp with TxnID = DBID (B2.4.3), chunked by DataID
  (B2.9.4), a re-send with AllowRetry = 0 and the granted PCrdType after
  RetryAck + PCrdGrant (B2.10);
* keeps an :class:`RNCache` (B4.1 states) that moves on completion by the
  Table B4.38 / B4.43 / B4.44 rows, and answers every snoop on RXSNP with
  the Table B4.46 to B4.50 expected response (SnpResp on TXRSP, or
  SnpRespData / SnpRespDataPtl on TXDAT);
* asserts TXSACTIVE from the first REQ flit until the last flit of every
  outstanding transaction and snoop (B14.7.2.1).

Sequence errors the transaction model reports (a CompAck the model would
have to send before a Comp, a second DBIDResp, ...) count in
``violations['txn_sequence']``.
"""

import random
from typing import Dict, Optional

from cocotb.triggers import Event, RisingEdge

from .chi_cache_model import RNCache
from .chi_config import CHIConfig
from .chi_flits import CHIDatFlit, CHIReqFlit, CHIRspFlit
from .chi_opcodes import (
    DatOpcode,
    MemAttr,
    ReqOpcode,
    RspOpcode,
    Size,
    SnpOpcode,
    data_windows,
    resp_encode,
)
from .chi_port import CHIPort
from .chi_transaction import REQ_CLASS, CHITransaction, ReqClass, RequesterTracker


class CHIRequestNode(CHIPort):
    """RN-F (or RN-I) BFM on one port."""

    def __init__(self, dut, title, prefix, clock, cfg: CHIConfig, node_id=0, home_id=0,
                 cache: Optional[RNCache] = None, seed=0, **port_kwargs):
        if not cfg.is_requester:
            raise ValueError(f"{title}: CHIRequestNode needs an RN node type, not {cfg.node_type.value}")
        super().__init__(dut, title, prefix, clock, cfg, **port_kwargs)
        self.node_id = node_id
        self.home_id = home_id
        self.cache = cache or RNCache()
        self.tracker = RequesterTracker(node_id)
        self.rng = random.Random(seed)
        self._events: Dict[int, Event] = {}
        self.completed = []
        self.snoops_seen = 0
        self.snoops_open = 0
        self.stats.update({'requests': 0, 'retries': 0, 'compacks': 0, 'write_data_flits': 0,
                           'snoop_resps': 0, 'snoop_resp_data': 0, 'read_data_flits': 0})

    # -- request API --------------------------------------------------------------
    def new_txn(self, opcode: ReqOpcode, addr: int, size=Size.B64, data: Optional[bytes] = None,
                be: Optional[int] = None, expcompack: Optional[int] = None, memattr=None,
                snpattr=None, order=0, likelyshared=0, excl=0, lpid=0, qos=0, cah=0, tgtid=None):
        """Build a transaction with the CHI defaults an RN-F would use."""
        size = Size(size) if not isinstance(size, Size) else size
        cls = REQ_CLASS[opcode]
        if memattr is None:
            memattr = (MemAttr.CACHEABLE | MemAttr.ALLOCATE | MemAttr.EWA) if cls in (
                ReqClass.READ_ALLOC, ReqClass.DATALESS, ReqClass.DATALESS_ACK, ReqClass.WRITE_COPYBACK) \
                or opcode in (ReqOpcode.WriteUniquePtl, ReqOpcode.WriteUniqueFull, ReqOpcode.ReadOnce) \
                else MemAttr.EWA
        if snpattr is None:
            snpattr = int(cls != ReqClass.PCRD_RETURN and opcode not in (
                ReqOpcode.ReadNoSnp, ReqOpcode.WriteNoSnpPtl, ReqOpcode.WriteNoSnpFull))
        if expcompack is None:
            expcompack = int(cls in (ReqClass.READ_ALLOC, ReqClass.DATALESS_ACK))
        if data is not None and be is None:
            be = (1 << len(data)) - 1
        return CHITransaction(opcode=opcode, addr=addr, size=size, txnid=None, srcid=self.node_id,
                              tgtid=self.home_id if tgtid is None else tgtid, expcompack=expcompack,
                              order=order, memattr=int(memattr), snpattr=snpattr, likelyshared=likelyshared,
                              excl=excl, lpid=lpid, qos=qos, cah=cah, data=data, be=be)

    def issue(self, txn: CHITransaction) -> CHITransaction:
        """Allocate a TxnID, send the REQ flit, return the (in-flight) transaction."""
        try:
            self.tracker.issue(txn)
        except ValueError as e:
            self._violation('txn_fields', f"{txn.opcode.name} at {txn.addr:#x}: {e}")
            raise
        self._events[txn.txnid] = Event()
        if txn.opcode in (ReqOpcode.Evict, ReqOpcode.CleanInvalid, ReqOpcode.MakeInvalid):
            # B4.7.2: the line must be I before one of these is issued
            self.cache.set_state(txn.addr, 'I')
        self._send_req(txn)
        self.stats['requests'] += 1
        return txn

    async def wait(self, txn: CHITransaction, timeout_cycles=100000) -> CHITransaction:
        ev = self._events.get(txn.txnid)
        if ev is None or txn.status in ('done', 'cancelled'):
            return txn
        for _ in range(timeout_cycles):
            if ev.is_set():
                return txn
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: {txn.opcode.name} TxnID {txn.txnid:#x} at {txn.addr:#x} "
                           f"not complete after {timeout_cycles} cycles (status {txn.status}, "
                           f"received {[f.opcode_name for _, f in txn.received]})")

    async def read(self, addr, opcode=ReqOpcode.ReadShared, size=Size.B64, **kw) -> CHITransaction:
        return await self.wait(self.issue(self.new_txn(opcode, addr, size, **kw)))

    async def write(self, addr, data: bytes, opcode=ReqOpcode.WriteNoSnpFull, be=None, **kw) -> CHITransaction:
        size = Size.of(len(data))
        return await self.wait(self.issue(self.new_txn(opcode, addr, size, data=bytes(data), be=be, **kw)))

    async def dataless(self, opcode: ReqOpcode, addr, **kw) -> CHITransaction:
        return await self.wait(self.issue(self.new_txn(opcode, addr, Size.B64, **kw)))

    async def writeback(self, addr, opcode=ReqOpcode.WriteBackFull, **kw) -> CHITransaction:
        """CopyBack write of the cached line (its data comes from the cache model)."""
        line = self.cache.line(addr)
        be = line.valid if opcode == ReqOpcode.WriteBackPtl else (1 << 64) - 1
        return await self.wait(self.issue(self.new_txn(opcode, addr & ~63, Size.B64,
                                                       data=bytes(line.data), be=be, **kw)))

    async def pcrd_return(self, pcrdtype: int):
        """B2.10.1: give back a Protocol Credit the completer granted."""
        txn = self.new_txn(ReqOpcode.PCrdReturn, 0, Size.B1, expcompack=0, snpattr=0, memattr=0)
        txn.allowretry, txn.pcrdtype = 0, pcrdtype
        self.tracker.issue(txn)
        self._send_req(txn)
        self.tracker.retired(txn)

    # -- flit builders --------------------------------------------------------------
    def _send_req(self, txn: CHITransaction):
        f = CHIReqFlit(self.cfg, qos=txn.qos, tgtid=txn.tgtid, srcid=txn.srcid, txnid=txn.txnid,
                       opcode=int(txn.opcode), size=int(txn.size), addr=txn.addr, likelyshared=txn.likelyshared,
                       allowretry=txn.allowretry, order=txn.order, pcrdtype=txn.pcrdtype, memattr=txn.memattr,
                       snpattr=txn.snpattr, lpid=txn.lpid, excl=txn.excl, expcompack=txn.expcompack)
        if txn.cah:
            f.cah = 1
        self.send('req', f)

    def _send_compack(self, tgtid, txnid, state: Optional[str] = None):
        f = CHIRspFlit(self.cfg, tgtid=tgtid, srcid=self.node_id, txnid=txnid, opcode=RspOpcode.CompAck,
                       resp=resp_encode(state) if state else 0)
        self.send('rsp', f)
        self.stats['compacks'] += 1

    def _data_flits(self, opcode: DatOpcode, tgtid, txnid, addr, data: bytes, be: int, resp=0,
                    homenid=0, dbid=0, resperr=0):
        """Chunk ``data`` (which starts at ``addr``) into DAT flits by DataID
        (B2.9.4 / Table B2.16): each flit carries the DW/8-byte window of the
        64-byte line its DataID names, every byte at its natural position,
        BE set only for the bytes in [addr, addr + len)."""
        flits = []
        for did, lo in data_windows(addr, len(data), self.cfg.data_width):
            dw = self.cfg.data_width // 8
            buf = bytearray(dw)
            mask = 0
            for i in range(dw):
                a = lo + i
                if addr <= a < addr + len(data) and (be >> (a - addr)) & 1:
                    buf[i] = data[a - addr]
                    mask |= 1 << i
            f = CHIDatFlit(self.cfg, tgtid=tgtid, srcid=self.node_id, txnid=txnid, opcode=int(opcode),
                           resp=resp, resperr=resperr, dataid=did, be=mask, homenid=homenid, dbid=dbid,
                           ccid=(addr >> 4) & 3)
            f.set_data_bytes(bytes(buf))
            flits.append(f)
        return flits

    # -- completion ------------------------------------------------------------------
    def _act(self, txn: CHITransaction, actions):
        for a in actions:
            k = a.kind
            if k == 'send_compack':
                state = None
                if txn.cls == ReqClass.WRITE_COPYBACK:
                    state, final = self.cache.compack_resp(txn.opcode, txn.addr)
                    self.cache.complete_write(txn.opcode, txn.addr, final)
                self._send_compack(a.tgtid, a.txnid, state)
            elif k == 'send_write_data':
                resp = 0
                if txn.cls == ReqClass.WRITE_COPYBACK:
                    st, final = self.cache.writedata_resp(txn.opcode, txn.addr)
                    resp = resp_encode(st)
                    self.cache.complete_write(txn.opcode, txn.addr, final)
                    if txn.data is None:
                        ln = self.cache.line(txn.addr)
                        txn.data = bytes(ln.data)
                        txn.be = ln.valid if txn.opcode == ReqOpcode.WriteBackPtl else (1 << 64) - 1
                else:
                    self.cache.complete_write(txn.opcode, txn.addr, 'I')
                for did, data_int, be in txn.write_chunks(self.cfg.data_width):
                    f = CHIDatFlit(self.cfg, tgtid=a.tgtid, srcid=self.node_id, txnid=a.txnid, opcode=int(a.opcode),
                                   resp=resp, dataid=did, be=be, ccid=(txn.addr >> 4) & 3)
                    f.fields['data'] = data_int
                    self.send('dat', f)
                    self.stats['write_data_flits'] += 1
            elif k == 'retry':
                self.stats['retries'] += 1
                self._send_req(txn)
            elif k == 'done':
                self._finish(txn)
            elif k == 'error':
                self._violation('txn_sequence', f"{txn.opcode.name} TxnID {txn.txnid:#x}: {a.text}")

    def _finish(self, txn: CHITransaction):
        if txn.cls == ReqClass.READ_ALLOC or (txn.cls == ReqClass.READ_NOALLOC and txn.nbytes == 64):
            st = txn.comp_state
            if st is not None:
                self.cache.complete_read(txn.opcode, txn.addr, st, txn.read_data())
        elif txn.cls in (ReqClass.DATALESS, ReqClass.DATALESS_ACK):
            if txn.comp_state is not None:
                self.cache.complete_dataless(txn.opcode, txn.addr, txn.comp_state)
        self.tracker.retired(txn)
        self.completed.append(txn)
        ev = self._events.pop(txn.txnid, None)
        if ev is not None:
            ev.set()

    # -- RX --------------------------------------------------------------------------
    def _on_rx(self, channel, flit):
        self._deliver(flit)
        if channel == 'rsp':
            txn, actions = self.tracker.route_rsp(flit)
            if txn is None:
                for a in actions:
                    if a.kind == 'error':
                        self._violation('txn_unknown', a.text)
                return
            self._act(txn, actions)
        elif channel == 'dat':
            txn, actions = self.tracker.route_dat(flit)
            if txn is None:
                for a in actions:
                    if a.kind == 'error':
                        self._violation('txn_unknown', a.text)
                return
            self.stats['read_data_flits'] += 1
            self._act(txn, actions)
        elif channel == 'snp':
            self._on_snoop(flit)

    def _on_snoop(self, snp):
        self.snoops_seen += 1
        addr = snp.byte_addr
        op = SnpOpcode(snp.opcode)
        r = self.cache.on_snoop(op, addr, rettosrc=snp.rettosrc, donotgotosd=snp.donotgotosd)
        if not r.with_data:
            f = CHIRspFlit(self.cfg, tgtid=snp.srcid, srcid=self.node_id, txnid=snp.txnid,
                           opcode=RspOpcode.SnpResp, resp=r.resp)
            self.send('rsp', f)
            self.stats['snoop_resps'] += 1
        else:
            op_d = DatOpcode.SnpRespDataPtl if r.partial else DatOpcode.SnpRespData
            for f in self._data_flits(op_d, snp.srcid, snp.txnid, addr & ~63, bytes(r.data), r.be,
                                      resp=r.resp):
                self.send('dat', f)
                self.stats['snoop_resp_data'] += 1

    def _reset_protocol(self):
        for txn in list(self.tracker.txns.values()):
            txn.status = 'cancelled'
            ev = self._events.pop(txn.txnid, None)
            if ev is not None:
                ev.set()
        self.tracker = RequesterTracker(self.node_id)
        self.snoops_open = 0

    # -- SACTIVE (B14.7.2.1) -----------------------------------------------------------------
    def _sactive(self):
        return int(self.have_work() or self.tracker.outstanding > 0)

    def summary(self):
        return (f"{self.title}: {self.stats['requests']} requests, {len(self.completed)} completed, "
                f"{self.stats['retries']} retries, {self.snoops_seen} snoops, "
                f"violations={self.all_violations() or 0}")


__all__ = ['CHIRequestNode']
