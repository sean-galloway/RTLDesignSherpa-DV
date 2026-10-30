# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_monitor
# Purpose: Passive CHI port monitor and protocol checker
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI monitor.

Watches one port, playing the same node the BFM beside it plays (its
``cfg.node_type``; the DUT's pins carry the far node's names, see
:class:`CHIPort`), and never drives. Every protocol
flit on every channel goes to ``_recvQ`` and the callbacks as a
:class:`CHIFlit` with ``channel`` and ``start_time`` set. Two layers of
checks, each counted in :attr:`violations` and logged, never raised:

* link (B13/B14, via :class:`chi_link.LinkChecker`): FLITV without
  FLITPEND the cycle before, a flit with no usable credit, more than
  ``max_lcredit`` outstanding, flits outside RUN/DEACTIVATE, credits
  outside RUN, LINKACTIVE ordering (B14.6.3.4), ACK dropped with credits
  held, LCrdReturn outside DEACTIVATE, LCrdReturn with TxnID != 0.
* transaction (B2, B4): every request seen on the REQ channel is tracked
  by (SrcID, TxnID) with :class:`chi_transaction.CHITransaction`; each
  response flit is fed to it and any ``error`` action it raises (CompAck
  before Comp, write data before a DBID, a second Comp, a reserved Resp
  encoding, ...) is a ``txn_sequence`` violation. Completed transactions
  go to :attr:`transactions`.

``max_credits[channel]`` is the peak transmitter credit count the monitor
modelled, which is how a test proves the credit pool was exercised.
"""

from collections import deque
from typing import Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge
from cocotb.utils import get_sim_time

from .chi_config import CHIConfig
from .chi_flits import flit_class
from .chi_link import LinkChecker, link_state
from .chi_opcodes import ReqOpcode, RspOpcode, Size, data_ids_for
from .chi_port import _int, bind_chi_signals
from .chi_transaction import CHITransaction, RequesterTracker, write_data_opcode


class CHIMonitor:
    """Passive CHI monitor + checker on one port."""

    def __init__(self, dut, title, prefix, clock, cfg: CHIConfig, reset=None, reset_active_low=True,
                 signal_map: Optional[Dict[str, str]] = None, log=None,
                 track_transactions=True, bus_name: str = '', deactivate_credit_grace: int = 1):
        cfg.validate()
        self.dut, self.title, self.prefix, self.clock, self.cfg = dut, title, prefix, clock, cfg
        self.bus_name = bus_name
        self.reset, self.reset_active_low = reset, reset_active_low
        self.log = log or getattr(dut, '_log', None)
        self.signal_map = dict(signal_map or {})
        self.track_transactions = track_transactions
        self.violations: Dict[str, int] = {}
        self.stats: Dict[str, int] = {'cycles': 0, 'flits': 0, 'lcrd_returns': 0, 'grants': 0,
                                      'activations': 0, 'deactivations': 0}
        self.opcode_counts: Dict[str, int] = {}
        self._recvQ = deque()
        self.callbacks: List[Callable] = []
        self.sig = bind_chi_signals(self, dut, title, prefix, bus_name, cfg,
                                    self.signal_map, self._wanted_signals(), self.log)
        # Table B14.2: a receiver "is permitted, but not required, to send
        # credits when first entering" DEACTIVATE, because it "could take some
        # time to react" (B14.5.1.1). A DUT that synchronizes LINKACTIVEREQ
        # over N flops and registers LCRDV grants for N + 1 cycles after the
        # pin falls; set the grace to that depth.
        self.checker = LinkChecker(max_credit=cfg.max_lcredit, tx_channels=cfg.tx_channels,
                                   rx_channels=cfg.rx_channels,
                                   deactivate_credit_grace=deactivate_credit_grace)
        self.txreq = self.txack = self.rxreq = self.rxack = 0
        # transaction tracking: the REQ channel's transmitter is the requester
        self._req_channel_dir = 'tx' if 'req' in cfg.tx_channels else 'rx'
        self.trackers: Dict[int, RequesterTracker] = {}
        self._dbids: Dict[tuple, CHITransaction] = {}
        self._snoops: Dict[int, object] = {}
        self.transactions: List[CHITransaction] = []
        self.count = 0
        self._task = cocotb.start_soon(self._run())

    # -- binding ----------------------------------------------------------------
    def _wanted_signals(self):
        names = []
        for ch in self.cfg.tx_channels:
            names += [f"tx{ch}flitpend", f"tx{ch}flitv", f"tx{ch}flit", f"tx{ch}lcrdv"]
        for ch in self.cfg.rx_channels:
            names += [f"rx{ch}flitpend", f"rx{ch}flitv", f"rx{ch}flit", f"rx{ch}lcrdv"]
        if self.cfg.link_control:
            names += ['txlinkactivereq', 'txlinkactiveack', 'rxlinkactivereq', 'rxlinkactiveack']
        if self.cfg.sactive:
            names += ['txsactive', 'rxsactive']
        return names

    def sig_read(self, name, default=0):
        return _int(self.sig.get(name), default)

    def in_reset(self):
        if self.reset is None:
            return False
        v = _int(self.reset, 0 if self.reset_active_low else 1)
        return (v == 0) if self.reset_active_low else (v == 1)

    # -- reporting ----------------------------------------------------------------
    def _violation(self, kind, msg):
        self.violations[kind] = self.violations.get(kind, 0) + 1
        if self.log:
            self.log.error(f"{self.title} CHI protocol: {msg} @ {get_sim_time('ns')}ns")

    def total_violations(self):
        return sum(self.violations.values()) + sum(self.checker.violations.values())

    def all_violations(self):
        out = dict(self.violations)
        for k, v in self.checker.violations.items():
            out[f"link.{k}"] = out.get(f"link.{k}", 0) + v
        return out

    @property
    def max_credits(self):
        return dict(self.checker.max_credits)

    def add_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def _deliver(self, flit):
        self._recvQ.append(flit)
        for cb in self.callbacks:
            cb(flit)

    @property
    def tx_state(self):
        return link_state(self.txreq, self.txack)

    @property
    def rx_state(self):
        return link_state(self.rxreq, self.rxack)

    # -- transaction layer ------------------------------------------------------------
    # The model (CHITransaction via RequesterTracker) tells the monitor what a
    # legal requester WOULD do next; the monitor then checks the wire actually
    # does it. _dbids holds every DBID handed to the requester that still owes
    # a CompAck or write data; _snoops every snoop that still owes a response.
    def _tracker(self, srcid):
        t = self.trackers.get(srcid)
        if t is None:
            t = self.trackers[srcid] = RequesterTracker(srcid)
        return t

    def _expect(self, txn, flit, ch):
        """After a response: register what the requester now owes."""
        op = flit.opcode
        if txn.dbid is None:
            return
        key = (txn.srcid, txn.dbid)
        if ch == 'rsp' and op in (RspOpcode.DBIDResp, RspOpcode.DBIDRespOrd, RspOpcode.CompDBIDResp) and txn.is_write:
            txn.expect_data = True
        if (ch == 'dat' and op in (0x4, 0xB)) or (ch == 'rsp' and op in (RspOpcode.Comp, RspOpcode.RespSepData,
                                                                           RspOpcode.CompDBIDResp, RspOpcode.DBIDResp,
                                                                           RspOpcode.DBIDRespOrd)):
            if txn.needs_compack or (ch == 'rsp' and op == RspOpcode.Comp and txn.cls.name == 'WRITE_COPYBACK'):
                txn.expect_ack = True
        if getattr(txn, 'expect_data', False) or getattr(txn, 'expect_ack', False):
            other = self._dbids.get(key)
            if other is not None and other is not txn and not self._settled(other):
                self._violation('dbid_reuse', f"DBID {txn.dbid:#x} to RN {txn.srcid} reused while "
                                              f"{other.opcode.name} TxnID {other.txnid:#x} still owes it (B2.4.3)")
            self._dbids[key] = txn

    @staticmethod
    def _settled(txn):
        return (not getattr(txn, 'expect_data', False) or getattr(txn, 'data_observed', False)) and \
               (not getattr(txn, 'expect_ack', False) or getattr(txn, 'ack_observed', False))

    def _owed(self, flit, what):
        txn = self._dbids.get((flit.srcid, flit.txnid))
        if txn is None:
            self._violation('txn_sequence', f"{what} TxnID {flit.txnid:#x} from {flit.srcid} matches no DBID "
                                            f"that still owes one (B2.4.3)")
        return txn

    def _on_req(self, flit):
        if flit.opcode == 0x05:                     # PCrdReturn: no transaction
            return
        tr = self._tracker(flit.srcid)
        old = tr.txns.get(flit.txnid)
        if old is not None:
            if old.status == 'retried':
                bad = []
                if flit.allowretry:
                    bad.append("AllowRetry must be 0")
                if flit.pcrdtype != old.pcrdtype:
                    bad.append(f"PCrdType {flit.pcrdtype} != granted {old.pcrdtype}")
                if flit.opcode != old.opcode or flit.addr != old.addr:
                    bad.append("opcode/address differ from the original")
                if bad:
                    self._violation('retry_resend', f"re-sent {old.opcode.name} TxnID {flit.txnid:#x}: "
                                                    + '; '.join(bad) + " (B2.10)")
                old.status = 'issued'
            elif old.status == 'retry_wait':
                self._violation('retry_resend', f"{old.opcode.name} TxnID {flit.txnid:#x} re-sent before "
                                                f"PCrdGrant (B2.10)")
            else:
                self._violation('txnid_reuse', f"REQ {flit.opcode_name} reuses TxnID {flit.txnid:#x} of an open "
                                               f"{old.opcode.name} from {flit.srcid} (B2.4.2)")
            return
        try:
            txn = CHITransaction(opcode=ReqOpcode(flit.opcode), addr=flit.addr, size=Size(flit.size),
                                 txnid=flit.txnid, srcid=flit.srcid, tgtid=flit.tgtid,
                                 expcompack=flit.expcompack, order=flit.order, memattr=flit.memattr,
                                 snpattr=flit.snpattr, likelyshared=flit.likelyshared, excl=flit.excl,
                                 lpid=flit.lpid, qos=flit.qos, allowretry=flit.allowretry,
                                 pcrdtype=flit.pcrdtype, cah=flit.cah, data_width=self.cfg.data_width)
            tr.issue(txn)
        except (ValueError, RuntimeError) as err:
            self._violation('txn_fields', f"REQ {flit.opcode_name} from {flit.srcid}: {err}")

    def _on_response(self, ch, flit):
        """RSP/DAT toward the requester: feed the model, record the obligations."""
        tr = self.trackers.get(flit.tgtid)
        if tr is None or (flit.txnid not in tr.txns and not (ch == 'rsp' and flit.opcode == RspOpcode.PCrdGrant)):
            self._violation('txn_unknown', f"{ch.upper()} {flit.opcode_name} to node {flit.tgtid} "
                                           f"TxnID {flit.txnid:#x} matches no request")
            return
        try:
            txn, actions = (tr.route_rsp(flit) if ch == 'rsp' else tr.route_dat(flit))
        except ValueError as err:                     # a reserved encoding (Table B13.35) or opcode
            self._violation('txn_sequence', f"{ch.upper()} {flit.opcode_name} to {flit.tgtid} TxnID "
                                            f"{flit.txnid:#x}: {err}")
            return
        for a in actions:
            if a.kind == 'error':
                self._violation('txn_sequence', f"{a.text} ({ch.upper()} {flit.opcode_name} src {flit.srcid} "
                                                f"txn {flit.txnid:#x})")
            elif a.kind == 'done' and txn is not None:
                self.transactions.append(txn)
        if txn is not None:
            self._expect(txn, flit, ch)

    def _on_from_requester(self, ch, flit):
        """RSP/DAT the requester sends: CompAck, write data, snoop responses."""
        op = flit.opcode
        if ch == 'rsp' and op == RspOpcode.CompAck:
            txn = self._owed(flit, 'CompAck')
            if txn is None:
                return
            if getattr(txn, 'ack_observed', False):
                self._violation('txn_sequence', f"CompAck twice for TxnID {flit.txnid:#x} from {flit.srcid}")
            elif not (txn.comp_seen or txn.respsep_seen):
                self._violation('txn_sequence', "CompAck before Comp/CompData/RespSepData (B2.7.3)")
            txn.ack_observed = True
        elif ch == 'dat' and op in (0x2, 0x3, 0xC, 0x7):
            txn = self._owed(flit, flit.opcode_name)
            if txn is None:
                return
            if not txn.dbid_seen:
                self._violation('txn_sequence', "write data before DBIDResp/CompDBIDResp (B2.3.2)")
            if op == 0x7:                                     # WriteDataCancel
                if txn.cls.name != 'WRITE_IMM':
                    self._violation('txn_sequence', "WriteDataCancel on a CopyBack write (B2.3.2.3)")
                txn.data_observed = True
            else:
                want = write_data_opcode(txn.opcode)
                if op == 0xC:
                    if want != 0x3:
                        self._violation('txn_sequence', "NonCopyBackWriteDataCompAck for a CopyBack write")
                    txn.ack_observed = True
                elif op != want:
                    self._violation('txn_sequence', f"{flit.opcode_name} for {txn.opcode.name}; Table B4.44 "
                                                    f"wants {want.name}")
                ids = data_ids_for(txn.nbytes, txn.addr, self.cfg.data_width)
                seen = getattr(txn, 'data_ids_seen', set())
                if flit.dataid not in ids:
                    self._violation('dataid', f"{flit.opcode_name} DataID {flit.dataid} not in {ids} for "
                                              f"{txn.nbytes} B at {txn.addr:#x} (B2.9.4)")
                elif flit.dataid in seen:
                    self._violation('dataid', f"{flit.opcode_name} DataID {flit.dataid} twice for TxnID {flit.txnid:#x}")
                seen = seen | {flit.dataid}
                txn.data_ids_seen = seen
                if seen >= set(ids):
                    txn.data_observed = True
        elif ch == 'rsp' and op == RspOpcode.SnpResp or ch == 'dat' and op in (0x1, 0x5, 0x6):
            snp = self._snoops.get(flit.txnid)
            if snp is None:
                self._violation('snoop_unknown', f"{flit.opcode_name} TxnID {flit.txnid:#x} from {flit.srcid} "
                                                 f"matches no outstanding snoop")
                return
            if ch == 'dat':
                ids = data_ids_for(64, snp.byte_addr, self.cfg.data_width)
                seen = getattr(snp, 'data_ids_seen', set())
                if flit.dataid not in ids or flit.dataid in seen:
                    self._violation('dataid', f"{flit.opcode_name} DataID {flit.dataid} for snoop TxnID "
                                              f"{flit.txnid:#x} ({'repeated' if flit.dataid in seen else 'illegal'})")
                seen = seen | {flit.dataid}
                snp.data_ids_seen = seen
                if seen >= set(ids):
                    del self._snoops[flit.txnid]
            else:
                del self._snoops[flit.txnid]
            self.stats['snoop_responses'] = self.stats.get('snoop_responses', 0) + 1

    @property
    def txsactive(self):
        return self.sig_read('txsactive') if 'txsactive' in self.sig else 0

    @property
    def rxsactive(self):
        return self.sig_read('rxsactive') if 'rxsactive' in self.sig else 0

    def _on_flit(self, direction, ch, flit):
        object.__setattr__(flit, 'direction', direction)      # 'tx' | 'rx' from this node's side
        self.stats['flits'] += 1
        key = f"{ch}.{flit.opcode_name}"
        self.opcode_counts[key] = self.opcode_counts.get(key, 0) + 1
        self._deliver(flit)
        if not self.track_transactions:
            return
        toward_requester = direction != self._req_channel_dir
        if ch == 'req':
            self._on_req(flit)
        elif ch == 'snp':
            if flit.txnid in self._snoops:
                self._violation('snoop_txnid_reuse', f"{flit.opcode_name} reuses TxnID {flit.txnid:#x} of an "
                                                     f"outstanding snoop")
            self._snoops[flit.txnid] = flit
        elif toward_requester:
            self._on_response(ch, flit)
        else:
            self._on_from_requester(ch, flit)

    def unfinished(self):
        """Transactions still open, and settled ones whose CompAck or write
        data the wire never showed. Call at the end of a test; a non-empty
        list is a verdict failure the per-flit checks cannot give."""
        out = []
        for tr in self.trackers.values():
            out += [f"open {t.opcode.name} TxnID {t.txnid:#x} ({t.status})" for t in tr.txns.values()]
        for (src, dbid), t in self._dbids.items():
            if not self._settled(t):
                owes = []
                if getattr(t, 'expect_ack', False) and not getattr(t, 'ack_observed', False):
                    owes.append('CompAck')
                if getattr(t, 'expect_data', False) and not getattr(t, 'data_observed', False):
                    owes.append('write data')
                out.append(f"{t.opcode.name} TxnID {t.txnid:#x} from {src} never sent {' and '.join(owes)} (DBID {dbid:#x})")
        out += [f"snoop {f.opcode_name} TxnID {f.txnid:#x} never answered" for f in self._snoops.values()]
        return out

    # -- loop -----------------------------------------------------------------------------
    async def _run(self):
        cfg = self.cfg
        pend_prev = {f"{d}{ch}": 0 for d, chs in (('tx', cfg.tx_channels), ('rx', cfg.rx_channels)) for ch in chs}
        while True:
            await FallingEdge(self.clock)
            if self.in_reset():
                self.checker.reset()
                self.txreq = self.txack = self.rxreq = self.rxack = 0
                self.trackers.clear()
                self._dbids.clear()
                self._snoops.clear()
                continue
            self.stats['cycles'] += 1
            flits, lcrdv = {}, {}
            for d, chs in (('tx', cfg.tx_channels), ('rx', cfg.rx_channels)):
                for ch in chs:
                    pend = self.sig_read(f"{d}{ch}flitpend")
                    v = self.sig_read(f"{d}{ch}flitv")
                    is_ret = False
                    if v:
                        flit = flit_class(ch).from_word(cfg, self.sig_read(f"{d}{ch}flit"))
                        self.count += 1
                        object.__setattr__(flit, 'count', self.count)
                        object.__setattr__(flit, 'start_time', get_sim_time('ns'))
                        is_ret = flit.is_lcrd_return
                        if is_ret:
                            self.stats['lcrd_returns'] += 1
                            if flit.txnid != 0:
                                self._violation('lcrd_return_txnid',
                                                f"{d.upper()}{ch.upper()} LCrdReturn TxnID {flit.txnid} != 0 (B13.11)")
                        else:
                            self._on_flit(d, ch, flit)
                    flits[f"{d}{ch}"] = (pend_prev[f"{d}{ch}"], v, is_ret)
                    pend_prev[f"{d}{ch}"] = pend
                    g = self.sig_read(f"{d}{ch}lcrdv")
                    lcrdv[f"{d}{ch}"] = g
                    self.stats['grants'] += g
            if cfg.link_control:
                txreq, txack = self.sig_read('txlinkactivereq'), self.sig_read('txlinkactiveack')
                rxreq, rxack = self.sig_read('rxlinkactivereq'), self.sig_read('rxlinkactiveack')
                if txreq and not self.txreq:
                    self.stats['activations'] += 1
                if not txreq and self.txreq:
                    self.stats['deactivations'] += 1
            else:
                txreq = txack = rxreq = rxack = 1
            self.checker.check(txreq, txack, rxreq, rxack, flits, lcrdv)
            self.txreq, self.txack, self.rxreq, self.rxack = txreq, txack, rxreq, rxack

    def summary(self):
        ops = ', '.join(f"{k}={v}" for k, v in sorted(self.opcode_counts.items()))
        return (f"{self.title}: {self.stats['flits']} flits, {len(self.transactions)} transactions, "
                f"violations={self.all_violations() or 0}, peak credits={self.max_credits}; {ops}")


__all__ = ['CHIMonitor']
