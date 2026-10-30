# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_hn
# Purpose: CHI Home Node model (memory + snoop filter + completer policy)
#          and the HN-F port BFM that serves one RN link from it
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI Home Node.

Two objects, so several ports can share one home:

* :class:`CHIHome` is the protocol: a byte-addressable ``MemoryModel``
  behind 64-byte lines, a precise :class:`SnoopFilter`, a
  :class:`CompleterTracker` for DBIDs and write-data / CompAck
  rendezvous (B2.4.3), and the policy knobs that pick between the flows
  the spec allows (B2.3): CompData vs RespSepData + DataSepResp for
  reads, CompDBIDResp vs DBIDResp + Comp for writes, Comp (Alt 1a) vs
  CompDBIDResp for a WriteEvictOrEvict / CAH copyback, and Request Retry
  (RetryAck then PCrdGrant, B2.10) at a configurable rate.
* :class:`CHIHomeNode` is one HN-F port facing one RN. It registers
  itself with the home under the RN's node ID so the home can snoop that
  RN (Table B4.26) when another RN's request needs it, serves every
  request on its RXREQ as a coroutine, and asserts TXSACTIVE while any
  transaction or snoop is open (B14.7.2.3).

Ordering (B2.7.3): the home serialises work per cache line, and holds a
line until the requester's CompAck (or the copyback's write data) has
arrived before it will snoop or serve that line again.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cocotb
from cocotb.triggers import Event, Lock, RisingEdge

from ..shared.memory_model import MemoryModel
from .chi_cache_model import LINE_BYTES, HomePolicy, SnoopFilter, line_addr
from .chi_config import CHIConfig
from .chi_flits import CHIDatFlit, CHIRspFlit, CHISnpFlit
from .chi_opcodes import (
    DatOpcode,
    ReqOpcode,
    RspOpcode,
    SnpOpcode,
    data_windows,
    resp_encode,
    resp_state,
)
from .chi_port import CHIPort
from .chi_transaction import REQ_CLASS, CompleterTracker, ReqClass, needs_compack


@dataclass
class HomeOptions:
    """Which of the spec's permitted flows this home uses, and how often."""
    read_separate: float = 0.0        # P(RespSepData + DataSepResp) instead of CompData
    write_separate: float = 0.0       # P(DBIDResp + Comp) instead of CompDBIDResp
    copyback_comp: float = 0.0        # P(Comp, Alt 1a) for WriteEvictOrEvict / CAH = 1
    retry_rate: float = 0.0           # P(RetryAck) for a request with AllowRetry = 1
    retry_grant_delay: int = 8        # cycles from RetryAck to PCrdGrant
    pcrdtype: int = 0                 # the one credit type this home uses (B2.10.2.2)
    comp_delay: tuple = (0, 0)        # extra cycles before the completion (min, max)
    snoop: bool = True                # send snoops the filter asks for
    wait_timeout: int = 20000         # cycles the home waits for CompAck / write data / a snoop response
                                      # before it gives up with a violation and frees the line


@dataclass
class _Snoop:
    rn_id: int
    opcode: SnpOpcode
    addr: int
    txnid: int
    done: Event = field(default_factory=Event)
    resp_state: Optional[str] = None
    data: Optional[bytearray] = None
    be: int = 0
    chunks: Dict[int, int] = field(default_factory=dict)
    expected: int = 0


class CHIHome:
    """The home-side protocol model shared by HN-F port BFMs."""

    def __init__(self, cfg: CHIConfig, memory: Optional[MemoryModel] = None, num_lines=1024,
                 options: Optional[HomeOptions] = None, node_id=0, seed=0, log=None):
        self.cfg = cfg
        self.memory = memory or MemoryModel(num_lines=num_lines, bytes_per_line=LINE_BYTES, log=log)
        self.sf = SnoopFilter()
        self.tracker = CompleterTracker()
        self.opt = options or HomeOptions()
        self.node_id = node_id
        self.rng = random.Random(seed)
        self.log = log
        self.ports: Dict[int, 'CHIHomeNode'] = {}
        self._line_locks: Dict[int, Lock] = {}
        self._snoop_txnid = 0
        self.open_snoops: Dict[tuple, _Snoop] = {}
        self.stats = {'requests': 0, 'reads': 0, 'writes': 0, 'dataless': 0, 'snoops': 0,
                      'retries': 0, 'pcrd_returned': 0, 'compacks': 0}

    # -- memory helpers ---------------------------------------------------------------
    def read_line(self, addr) -> bytearray:
        return bytearray(self.memory.read(line_addr(addr), LINE_BYTES))

    def write_bytes(self, addr, data: bytes, be: int):
        """Byte-enabled write at ``addr`` (bytes with BE clear are left alone)."""
        be &= (1 << len(data)) - 1
        if not be:
            return
        self.memory.write(addr, bytearray(data), be)

    def line_lock(self, addr) -> Lock:
        k = line_addr(addr)
        lk = self._line_locks.get(k)
        if lk is None:
            lk = self._line_locks[k] = Lock()
        return lk

    def register(self, rn_id: int, port: 'CHIHomeNode'):
        self.ports[rn_id] = port

    def next_snoop_txnid(self):
        self._snoop_txnid = (self._snoop_txnid + 1) & 0xFFF
        return self._snoop_txnid

    # -- waiting ----------------------------------------------------------------------------
    async def wait_for(self, event: Event, port: 'CHIHomeNode', what: str) -> bool:
        """Await ``event`` for at most ``opt.wait_timeout`` cycles. A timeout
        is a ``timeout`` violation on ``port`` (the other side never sent
        what the flow needs) and returns False so the caller frees the line."""
        for _ in range(self.opt.wait_timeout):
            if event.is_set():
                return True
            await RisingEdge(port.clock)
        if event.is_set():
            return True
        port._violation('timeout', f"{what} not received within {self.opt.wait_timeout} cycles")
        return False

    # -- snooping ---------------------------------------------------------------------------
    async def snoop(self, rn_id: int, opcode: SnpOpcode, addr: int, rettosrc=0) -> _Snoop:
        port = self.ports.get(rn_id)
        if port is None:
            raise KeyError(f"home: no port registered for RN {rn_id}; cannot snoop it")
        s = _Snoop(rn_id, opcode, line_addr(addr), self.next_snoop_txnid())
        self.open_snoops[(rn_id, s.txnid)] = s
        port.send_snoop(s, rettosrc)
        self.stats['snoops'] += 1
        ok = await self.wait_for(s.done, port, f"{opcode.name} response from RN {rn_id} for {s.addr:#x}")
        self.open_snoops.pop((rn_id, s.txnid), None)
        if not ok or s.resp_state is None:
            return s
        self.sf.on_snoop_response(rn_id, s.addr, s.resp_state.replace('_PD', ''))
        if s.data is not None and s.resp_state.endswith('_PD'):
            self.write_bytes(s.addr, bytes(s.data), s.be)       # dirty data passed to Home
        return s

    async def snoop_for(self, opcode: ReqOpcode, addr: int, requester: int) -> List[_Snoop]:
        if not self.opt.snoop:
            return []
        results = []
        for rn_id, snp in self.sf.snoops_for(opcode, addr, requester):
            results.append(await self.snoop(rn_id, snp, addr))
        return results


class CHIHomeNode(CHIPort):
    """HN-F port BFM: serves one RN link from a :class:`CHIHome`."""

    def __init__(self, dut, title, prefix, clock, cfg: CHIConfig, home: Optional[CHIHome] = None,
                 rn_id=0, **port_kwargs):
        if not cfg.is_home:
            raise ValueError(f"{title}: CHIHomeNode needs an HN node type, not {cfg.node_type.value}")
        super().__init__(dut, title, prefix, clock, cfg, **port_kwargs)
        self.home = home or CHIHome(cfg, log=self.log)
        self.rn_id = rn_id
        self.home.register(rn_id, self)
        self.open: Dict[tuple, object] = {}     # (srcid, txnid) -> tracker entry
        self.served = []
        self.stats.update({'requests': 0, 'served': 0, 'snoops_sent': 0, 'retries': 0})

    @property
    def node_id(self):
        return self.home.node_id

    # -- flit builders ---------------------------------------------------------------------
    def _rsp(self, entry, opcode: RspOpcode, resp=0, dbid=0, pcrdtype=0, resperr=0):
        return CHIRspFlit(self.cfg, tgtid=entry.srcid, srcid=self.node_id, txnid=entry.txnid,
                          opcode=int(opcode), resp=resp, dbid=dbid, pcrdtype=pcrdtype, resperr=resperr)

    def _data_flits(self, entry, opcode: DatOpcode, data: bytes, resp=0, dbid=0, resperr=0):
        flits = []
        dw = self.cfg.data_width // 8
        lo_all = line_addr(entry.addr)
        for did, lo in data_windows(entry.addr, entry.nbytes, self.cfg.data_width):
            window = data[lo - lo_all: lo - lo_all + dw]
            f = CHIDatFlit(self.cfg, tgtid=entry.srcid, srcid=self.node_id, txnid=entry.txnid,
                           opcode=int(opcode), resp=resp, resperr=resperr, dataid=did, dbid=dbid,
                           homenid=self.node_id, ccid=(entry.addr >> 4) & 3, be=(1 << dw) - 1)
            f.set_data_bytes(bytes(window))
            flits.append(f)
        return flits

    def send_snoop(self, s: _Snoop, rettosrc=0):
        f = CHISnpFlit(self.cfg, srcid=self.node_id, txnid=s.txnid, opcode=int(s.opcode),
                       addr=s.addr >> 3, rettosrc=rettosrc)
        self.send('snp', f)
        self.stats['snoops_sent'] += 1

    # -- RX -------------------------------------------------------------------------------
    def _reset_protocol(self):
        for e in self.open.values():
            for ev in (getattr(e, 'compack_event', None), getattr(e, 'data_event', None)):
                if ev is not None:
                    ev.set()
        self.open.clear()
        for s in list(self.home.open_snoops.values()):
            if s.rn_id == self.rn_id:
                s.done.set()
        self.home.tracker = CompleterTracker()

    def _on_rx(self, channel, flit):
        self._deliver(flit)
        if channel == 'req':
            self.stats['requests'] += 1
            self.home.stats['requests'] += 1
            if flit.srcid != self.rn_id and 'rn_id_mismatch' not in self.violations:
                self._violation('rn_id_mismatch', f"REQ SrcID {flit.srcid} on the port registered for RN "
                                                  f"{self.rn_id}; snoops to this RN would never match")
            cocotb.start_soon(self._serve(flit))
        elif channel == 'rsp':
            self._on_rsp(flit)
        elif channel == 'dat':
            self._on_dat(flit)

    def _on_rsp(self, flit):
        op = flit.opcode
        if op == RspOpcode.CompAck:
            try:
                e = self.home.tracker.on_compack(flit)
            except (LookupError, ValueError) as err:
                self._violation('txn_sequence', str(err))
                return
            self.home.stats['compacks'] += 1
            e.compack_event.set()
        elif op == RspOpcode.SnpResp:
            s = self.home.open_snoops.get((flit.srcid, flit.txnid))
            if s is None:
                self._violation('txn_unknown', f"SnpResp TxnID {flit.txnid:#x} from {flit.srcid} matches no snoop")
                return
            s.resp_state = resp_state('snoop', flit.resp)
            s.done.set()
        else:
            self._violation('txn_unexpected', f"unexpected RSP {flit.opcode_name} at Home from {flit.srcid}")

    def _on_dat(self, flit):
        op = flit.opcode
        if op in (DatOpcode.SnpRespData, DatOpcode.SnpRespDataPtl):
            s = self.home.open_snoops.get((flit.srcid, flit.txnid))
            if s is None:
                self._violation('txn_unknown', f"{flit.opcode_name} TxnID {flit.txnid:#x} matches no snoop")
                return
            if s.data is None:
                s.data = bytearray(LINE_BYTES)
                s.expected = len(data_windows(s.addr, LINE_BYTES, self.cfg.data_width))
            legal = [d for d, _ in data_windows(s.addr, LINE_BYTES, self.cfg.data_width)]
            if flit.dataid not in legal or flit.dataid in s.chunks:
                self._violation('snoop_dataid', f"{flit.opcode_name} DataID {flit.dataid} from RN {flit.srcid}: "
                                                f"{'repeated' if flit.dataid in s.chunks else 'not one of ' + str(legal)} (B2.9.4)")
                return
            dw = self.cfg.data_width // 8
            lo = {128: flit.dataid * 16, 256: (flit.dataid >> 1) * 32, 512: 0}[self.cfg.data_width]
            s.data[lo:lo + dw] = flit.data_bytes()
            s.be |= int(flit.be) << lo
            s.chunks[flit.dataid] = 1
            s.resp_state = resp_state('snoop', flit.resp)
            if len(s.chunks) >= s.expected:
                s.done.set()
        elif op == DatOpcode.WriteDataCancel:
            # B2.3.2.1: the requester cancels instead of sending data (Immediate Write only)
            e = self.home.tracker.by_dbid(flit.srcid, flit.txnid)
            if e is None or e.cls != ReqClass.WRITE_IMM:
                self._violation('txn_sequence', f"WriteDataCancel TxnID {flit.txnid:#x} from {flit.srcid} "
                                               f"matches no Immediate Write DBID")
                return
            e.cancelled = True
            e.data_event.set()
        elif op in (DatOpcode.NonCopyBackWriteData, DatOpcode.CopyBackWriteData,
                    DatOpcode.NonCopyBackWriteDataCompAck):
            try:
                e = self.home.tracker.on_write_data(flit)
            except (LookupError, ValueError) as err:
                self._violation('txn_sequence', str(err))
                return
            if op == DatOpcode.NonCopyBackWriteDataCompAck:
                e.compack_event.set()
            if e.write_complete:
                e.data_event.set()
        else:
            self._violation('txn_unexpected', f"unexpected DAT {flit.opcode_name} at Home from {flit.srcid}")

    # -- serving ------------------------------------------------------------------------------
    async def _delay(self):
        lo, hi = self.home.opt.comp_delay
        for _ in range(self.home.rng.randint(lo, hi) if hi else 0):
            await RisingEdge(self.clock)

    async def _serve(self, req):
        home, opt = self.home, self.home.opt
        opcode = ReqOpcode(req.opcode)
        if opcode == ReqOpcode.PCrdReturn:
            home.stats['pcrd_returned'] += 1
            return
        if opcode not in REQ_CLASS:
            self._violation('unsupported', f"REQ {req.opcode_name} is outside this family's scope; no response sent")
            return
        try:
            e = home.tracker.accept(req)
        except ValueError as err:
            self._violation('txn_fields', str(err))
            return
        e.compack_event, e.data_event, e.cancelled = Event(), Event(), False
        key = (e.srcid, e.txnid)
        self.open[key] = e
        try:
            if req.allowretry and opt.retry_rate and home.rng.random() < opt.retry_rate:
                self.send('rsp', self._rsp(e, RspOpcode.RetryAck, pcrdtype=opt.pcrdtype))
                self.stats['retries'] += 1
                home.stats['retries'] += 1
                for _ in range(opt.retry_grant_delay):
                    await RisingEdge(self.clock)
                self.send('rsp', self._rsp(e, RspOpcode.PCrdGrant, pcrdtype=opt.pcrdtype))
                return
            lock = home.line_lock(e.addr)
            await lock.acquire()
            try:
                await self._delay()
                cls = REQ_CLASS[opcode]
                if cls in (ReqClass.READ_ALLOC, ReqClass.READ_NOALLOC):
                    await self._serve_read(e, opcode)
                elif cls in (ReqClass.DATALESS, ReqClass.DATALESS_ACK):
                    await self._serve_dataless(e, opcode)
                elif cls == ReqClass.WRITE_IMM:
                    await self._serve_write(e, opcode)
                elif cls == ReqClass.WRITE_COPYBACK:
                    await self._serve_copyback(e, opcode)
            finally:
                lock.release()
        finally:
            self.open.pop(key, None)
            home.tracker.retire(e)
            self.served.append(e)
            self.stats['served'] += 1

    async def _serve_read(self, e, opcode):
        home = self.home
        home.stats['reads'] += 1
        before = home.sf.sharers(e.addr).get(e.srcid, 'I')
        snoops = await home.snoop_for(opcode, e.addr, e.srcid)
        dirty_passed = any(s.resp_state and s.resp_state.endswith('_PD') for s in snoops)
        others = any(st != 'I' for rn, st in home.sf.sharers(e.addr).items() if rn != e.srcid)
        state = HomePolicy.read_response_state(opcode, before, others, dirty_passed)
        line = home.read_line(e.addr)
        data = bytes(line)
        resp = resp_encode(state)
        ack = needs_compack(opcode, e.expcompack)
        dbid = home.tracker.allocate_dbid(e) if ack else 0
        if home.rng.random() < home.opt.read_separate:
            self.send('rsp', self._rsp(e, RspOpcode.RespSepData, dbid=dbid))
            for f in self._data_flits(e, DatOpcode.DataSepResp, data, resp=resp, dbid=dbid):
                self.send('dat', f)
        else:
            for f in self._data_flits(e, DatOpcode.CompData, data, resp=resp, dbid=dbid):
                self.send('dat', f)
        final = state.replace('_PD', '') if state != 'I' else 'I'
        home.sf.on_complete(e.srcid, e.addr, final)
        if ack:
            await home.wait_for(e.compack_event, self, f"CompAck for {opcode.name} TxnID {e.txnid:#x}")

    async def _serve_dataless(self, e, opcode):
        home = self.home
        home.stats['dataless'] += 1
        before = home.sf.sharers(e.addr).get(e.srcid, 'I')
        await home.snoop_for(opcode, e.addr, e.srcid)
        state = HomePolicy.dataless_response_state(opcode, before)
        ack = needs_compack(opcode, e.expcompack)
        dbid = home.tracker.allocate_dbid(e) if ack else 0
        self.send('rsp', self._rsp(e, RspOpcode.Comp, resp=resp_encode(state), dbid=dbid))
        # Table B4.43 final states: MakeUnique -> UD; CleanUnique from I -> UCE, SC -> UC, SD -> UD
        if state == 'I':
            final = 'I'
        elif opcode == ReqOpcode.MakeUnique:
            final = 'UD'
        elif opcode == ReqOpcode.CleanUnique:
            final = {'I': 'UCE', 'SC': 'UC', 'SD': 'UD'}.get(before, before)
        else:
            final = state
        home.sf.on_complete(e.srcid, e.addr, final)
        if ack:
            await home.wait_for(e.compack_event, self, f"CompAck for {opcode.name} TxnID {e.txnid:#x}")

    async def _serve_write(self, e, opcode):
        home = self.home
        home.stats['writes'] += 1
        await home.snoop_for(opcode, e.addr, e.srcid)
        dbid = home.tracker.allocate_dbid(e)
        separate = home.rng.random() < home.opt.write_separate
        if separate:
            self.send('rsp', self._rsp(e, RspOpcode.DBIDResp, dbid=dbid))
        else:
            self.send('rsp', self._rsp(e, RspOpcode.CompDBIDResp, dbid=dbid))
        if not await home.wait_for(e.data_event, self, f"write data for {opcode.name} TxnID {e.txnid:#x}"):
            return
        if not e.cancelled:
            self._apply_write(e)
        if separate:
            self.send('rsp', self._rsp(e, RspOpcode.Comp, dbid=dbid))
        if e.expcompack:
            await home.wait_for(e.compack_event, self, f"CompAck for {opcode.name} TxnID {e.txnid:#x}")

    async def _serve_copyback(self, e, opcode):
        home = self.home
        home.stats['writes'] += 1
        no_data = (opcode == ReqOpcode.WriteEvictOrEvict or e.cah) and \
            home.rng.random() < home.opt.copyback_comp
        if no_data:
            dbid = home.tracker.allocate_dbid(e)
            self.send('rsp', self._rsp(e, RspOpcode.Comp, dbid=dbid))
            await home.wait_for(e.compack_event, self, f"CompAck for {opcode.name} TxnID {e.txnid:#x}")
            home.sf.on_complete(e.srcid, e.addr, 'I')
            return
        dbid = home.tracker.allocate_dbid(e)
        self.send('rsp', self._rsp(e, RspOpcode.CompDBIDResp, dbid=dbid))
        if not await home.wait_for(e.data_event, self, f"CopyBackWriteData for {opcode.name} TxnID {e.txnid:#x}"):
            return
        st = e.writedata_state
        if st and st.endswith('_PD'):
            self._apply_write(e)
        final = 'I' if opcode in (ReqOpcode.WriteBackFull, ReqOpcode.WriteBackPtl, ReqOpcode.WriteEvictFull,
                                  ReqOpcode.WriteEvictOrEvict) else (st.replace('_PD', '') if st else 'I')
        if final == 'UD':
            final = 'UC'
        home.sf.on_complete(e.srcid, e.addr, final)

    def _apply_write(self, e):
        dw = self.cfg.data_width // 8
        for did, (data_int, be, _resp) in sorted(e.data_chunks.items()):
            lo = {128: did * 16, 256: (did >> 1) * 32, 512: 0}[self.cfg.data_width]
            self.home.write_bytes(line_addr(e.addr) + lo, data_int.to_bytes(dw, 'little'), be)

    # -- SACTIVE (B14.7.2.3) ------------------------------------------------------------------
    def _sactive(self):
        return int(self.have_work() or bool(self.open) or bool(self.home.open_snoops))

    def summary(self):
        return (f"{self.title}: {self.stats['requests']} requests, {self.stats['served']} served, "
                f"{self.stats['snoops_sent']} snoops, {self.stats['retries']} retries, "
                f"violations={self.all_violations() or 0}")


__all__ = ['CHIHome', 'CHIHomeNode', 'HomeOptions']
