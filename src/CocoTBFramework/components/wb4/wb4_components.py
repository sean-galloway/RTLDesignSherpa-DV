# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: WB4Monitor / WB4Slave / WB4Master
# Purpose: Wishbone B4 PIPELINED BFMs on the cocotb_bus chassis
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-09-09
"""Wishbone B4 (pipelined) Monitor, Slave and Master BFMs.

Same chassis as the APB family (``BusDriver`` / ``BusMonitor``), same shared
parts as every other family (``FlexRandomizer`` timing, ``MemoryModel``,
``Packet``). Wishbone is not a plain valid/ready pair, which is why these are
not GAXI compositions: STALL is an inverted ready that may assert with no
request pending, CYC is an envelope over the whole cycle, and a termination
(ACK / ERR / RTY, one per clock, no ready) pairs with the OLDEST accepted
request.

Timing convention (matches the APB BFMs): outputs change right after the
rising edge; inputs are sampled at the falling edge plus 200 ps, i.e. the
value the next rising edge will see. A request is accepted on the rising edge
where ``CYC && STB && !STALL``; a termination is taken on the rising edge
where one of ``ACK/ERR/RTY`` is high.
"""

from collections import deque
from typing import Callable, Optional

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time
from cocotb_bus.drivers import BusDriver
from cocotb_bus.monitors import BusMonitor

from ..shared.flex_randomizer import FlexRandomizer
from ..shared.memory_model import MemoryModel
from ..shared.wb4_common import (
    WB4_DATA_ALIASES,
    WB4_MASTER_DRIVEN,
    WB4_OPTIONAL_SIGNALS,
    WB4_SLAVE_DRIVEN,
    WB4_STATUS_ACK,
    WB4_STATUS_ERR,
    WB4_STATUS_NAMES,
    WB4_STATUS_RTY,
)
from .wb4_packet import WB4Packet

_SETTLE_PS = 200


def _int(sig, default=0):
    v = sig.value
    return v.integer if v.is_resolvable else default


class WB4SignalMixin:
    """Signal-list handling shared by the three BFMs.

    ``cocotb_bus`` binds ``_signals`` as required and ``_optional_signals``
    as best-effort. The data signals have two legal names each (the spec's
    DAT_O/DAT_I read differently from each side), so they are resolved
    against the DUT at bind time and passed to cocotb_bus under their
    canonical names ``DAT_W`` / ``DAT_R``. ERR and RTY are optional: a slave
    that only ever ACKs need not have them.
    """

    @staticmethod
    def _has(entity, prefix, suffix):
        want = f"{prefix}_{suffix}".lower()
        for name in dir(entity):
            if name.lower() == want:
                return name
        return None

    @classmethod
    def _resolve(cls, entity, prefix, signals):
        """Return (required list, optional list, alias map) for cocotb_bus."""
        if signals:
            return list(signals), [], {}
        required = list(WB4_MASTER_DRIVEN) + list(WB4_SLAVE_DRIVEN)
        aliases = {}
        for canon, options in WB4_DATA_ALIASES.items():
            for opt in options:
                actual = cls._has(entity, prefix, opt)
                if actual:
                    aliases[canon] = actual[len(prefix) + 1:]
                    break
            else:
                raise AttributeError(
                    f"{prefix}: none of {options} found on the DUT for {canon}")
            required.append(canon)
        optional = {}
        for sig in WB4_OPTIONAL_SIGNALS:
            actual = cls._has(entity, prefix, sig)
            if actual:
                optional[sig] = actual[len(prefix) + 1:]
        return required, optional, aliases

    def is_signal_present(self, name):
        return hasattr(self.bus, name) and getattr(self.bus, name) is not None

    def _term_bits(self):
        ack = _int(self.bus.ACK)
        err = _int(self.bus.ERR) if self.is_signal_present('ERR') else 0
        rty = _int(self.bus.RTY) if self.is_signal_present('RTY') else 0
        return ack, err, rty


def _status_of(ack, err, rty):
    if err:
        return WB4_STATUS_ERR
    if rty:
        return WB4_STATUS_RTY
    return WB4_STATUS_ACK if ack else None


class _WB4BusMixin(WB4SignalMixin):
    """Common construction for the BusMonitor-based components."""

    def _init_bus(self, base, entity, title, prefix, clock, signals, log,
                  addr_width, data_width, **kwargs):
        prefix = prefix.rstrip('_')
        req, opt, aliases = self._resolve(entity, prefix, signals)
        # cocotb_bus accepts dicts mapping canonical->actual for renames.
        self._signals = {s: aliases.get(s, s) for s in req}
        self._optional_signals = opt
        base.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        self.title = title
        self.prefix = prefix
        self.log = log or entity._log
        self.addr_width = addr_width
        self.data_width = data_width
        self.sel_width = data_width // 8


class WB4Monitor(_WB4BusMixin, BusMonitor):
    """Passive Wishbone B4 monitor.

    Emits one :class:`WB4Packet` per TERMINATED transfer, with the request
    fields captured at accept and the termination fields at ACK/ERR/RTY,
    paired in order. Carries the pipelined-protocol checks; a violation is
    counted in :attr:`violations` and logged, never raised, so a test decides
    how loud to be. ``max_inflight`` records the peak outstanding count,
    which is how a test proves the pipelined mode was exercised.
    """

    def __init__(self, entity, title, prefix, clock, signals=None,
                 addr_width=32, data_width=32, classic=False, log=None, **kwargs):
        self._init_bus(BusMonitor, entity, title, prefix, clock, signals, log,
                       addr_width, data_width, **kwargs)
        # B4 standard ("classic") mode: the master holds STB until the
        # termination and there is no STALL, so a request is one PRESENTATION,
        # accepted once, not once per clock it is held.
        self.classic = classic
        self.count = 0
        self.inflight = deque()          # accepted, not terminated (WB4Packet)
        self.accepted = 0
        self.terminated = 0
        self.aborts = 0
        self.max_inflight = 0
        self.violations = {}             # kind -> count
        self._prev = None                # last sampled request while stalled

    def _violation(self, kind, msg):
        self.violations[kind] = self.violations.get(kind, 0) + 1
        self.log.error(f"{self.title} WB4 protocol: {msg}")

    def total_violations(self):
        return sum(self.violations.values())

    def _sample_request(self):
        return (_int(self.bus.WE), _int(self.bus.ADR), _int(self.bus.DAT_W), _int(self.bus.SEL))

    async def _monitor_recv(self):
        while True:
            await FallingEdge(self.clock)
            await Timer(_SETTLE_PS, units='ps')
            cyc, stb, stall = _int(self.bus.CYC), _int(self.bus.STB), _int(self.bus.STALL)
            ack, err, rty = self._term_bits()
            now = get_sim_time('ns')

            if stb and not cyc:
                self._violation('stb_without_cyc', "STB asserted without CYC")
            if ack + err + rty > 1:
                self._violation('multi_term', f"more than one of ACK/ERR/RTY (ack={ack} err={err} rty={rty})")

            # A pending request must be held unchanged: while STALLed in
            # pipelined mode, until terminated in classic mode.
            req = self._sample_request() if (cyc and stb) else None
            if self._prev is not None and cyc:
                if not stb:
                    self._violation('request_dropped', "request withdrawn before it was accepted")
                elif req != self._prev:
                    self._violation('request_changed', "request changed before it was accepted")
            # (a request withdrawn by dropping CYC is the abort case, counted below)
            status_now = _status_of(ack, err, rty)
            if self.classic:
                self._prev = req if (cyc and stb and status_now is None) else None
            else:
                self._prev = req if (cyc and stb and stall) else None

            # Abort: CYC low with transfers outstanding.
            if not cyc and self.inflight:
                self.aborts += 1
                self.log.warning(f"{self.title} WB4: CYC dropped with {len(self.inflight)} outstanding -- aborted")
                self.inflight.clear()

            status = _status_of(ack, err, rty)
            if status is not None:
                if not cyc:
                    self._violation('term_outside_cyc', f"{WB4_STATUS_NAMES[status]} outside a cycle")
                elif not self.inflight:
                    self._violation('term_without_request', f"{WB4_STATUS_NAMES[status]} with nothing outstanding")
                else:
                    pkt = self.inflight.popleft()
                    pkt.fields['status'] = status
                    pkt.fields['dat_r'] = _int(self.bus.DAT_R)
                    object.__setattr__(pkt, 'end_time', now)
                    self.terminated += 1
                    self._recv(pkt)
                    self.log.debug(f"{self.title} WB4 #{pkt.count}: {pkt.formatted(compact=True)}")

            # Classic: a presentation is accepted once, and never in the clock
            # its termination is on the wire (the master sees that termination
            # at the next edge, so STB is still held).
            accept = ((cyc and stb and not self.inflight and status is None) if self.classic
                      else (cyc and stb and not stall))
            if accept:
                we, adr, dat_w, sel = req
                self.count += 1
                pkt = WB4Packet(addr_width=self.addr_width, data_width=self.data_width,
                                sel_width=self.sel_width, we=we, adr=adr, dat_w=dat_w, sel=sel,
                                count=self.count, start_time=now)
                self.inflight.append(pkt)
                self.accepted += 1
                self.max_inflight = max(self.max_inflight, len(self.inflight))


class WB4Slave(_WB4BusMixin, BusMonitor):
    """Wishbone B4 pipelined slave (responder) over a :class:`MemoryModel`.

    Slave-via-BusMonitor, the framework convention: the sampling chassis is
    reused and the loop also drives ``STALL``, ``ACK``/``ERR``/``RTY`` and
    ``DAT_R``. Every accepted request is answered IN ORDER after a
    randomized latency.

    Randomizer keys:
        ``stall``  clocks of STALL inserted after each accept (0 = none)
        ``ack``    termination latency in clocks, >= 1 (registered)
        ``status`` termination: 0 ACK, 1 ERR, 2 RTY (weighted)

    ``status_hook(packet) -> status | None`` overrides the randomizer per
    request (an address window that errors, a retry-once model, ...).
    ``max_outstanding`` stalls when that many requests await termination.
    A master that drops CYC with requests outstanding aborts them: the
    pending responses are discarded.
    """

    def __init__(self, entity, title, prefix, clock, registers=None, signals=None,
                 addr_width=32, data_width=32, num_lines=1024, randomizer=None,
                 max_outstanding=16, status_hook: Optional[Callable] = None,
                 classic=False, log=None, **kwargs):
        self._init_bus(BusMonitor, entity, title, prefix, clock, signals, log,
                       addr_width, data_width, **kwargs)
        self.randomizer = randomizer or FlexRandomizer(self._default_randomizer_constraints())
        # Classic: never STALL, accept a presentation once, one outstanding;
        # the master holds STB until it sees the termination.
        self.classic = classic
        self.max_outstanding = 1 if classic else max_outstanding
        self.status_hook = status_hook
        self.bytes_per_line = self.sel_width
        preset = registers
        if preset is not None:
            num_lines = max(num_lines, len(preset) // self.bytes_per_line)
        self.mem = MemoryModel(num_lines=num_lines, bytes_per_line=self.bytes_per_line,
                               log=self.log, preset_values=preset)
        self.count = 0
        self.outstanding = 0
        self.sentQ = deque()             # completed packets, in order
        self._pending = deque()          # (due_clock, packet)
        self._clock_no = 0
        self._stall_left = 0
        self.stats = {'accepted': 0, 'ack': 0, 'err': 0, 'rty': 0, 'aborted': 0}
        self.bus.STALL.setimmediatevalue(0)
        self.bus.ACK.setimmediatevalue(0)
        if self.is_signal_present('ERR'):
            self.bus.ERR.setimmediatevalue(0)
        if self.is_signal_present('RTY'):
            self.bus.RTY.setimmediatevalue(0)
        self.bus.DAT_R.setimmediatevalue(0)

    @staticmethod
    def _default_randomizer_constraints():
        return {
            'stall':  ([(0, 0), (1, 2), (3, 6)], [8, 2, 1]),
            'ack':    ([(1, 1), (2, 4)], [6, 1]),
            'status': ([(0, 0), (1, 1), (2, 2)], [20, 1, 1]),
        }

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer
        self.log.info(f"Set new randomizer for WB4 Slave ({self.title})")

    def reset_registers(self):
        self.mem.reset(to_preset=True)

    async def reset_bus(self):
        self.bus.STALL.value = 0
        self.bus.ACK.value = 0
        if self.is_signal_present('ERR'):
            self.bus.ERR.value = 0
        if self.is_signal_present('RTY'):
            self.bus.RTY.value = 0
        self.bus.DAT_R.value = 0
        self._pending.clear()
        self.outstanding = 0

    def _line_addr(self, adr):
        return adr & ~(self.bytes_per_line - 1) & ((1 << self.addr_width) - 1)

    def _service(self, pkt, rnd):
        """Apply the request to the memory model; fill dat_r; pick the status."""
        status = None
        if self.status_hook is not None:
            status = self.status_hook(pkt)
        if status is None:
            status = int(rnd.get('status', 0)) & 3
        pkt.fields['status'] = status
        if status == WB4_STATUS_ACK:
            line = self._line_addr(int(pkt.fields['adr']))
            if int(pkt.fields['we']):
                data = self.mem.integer_to_bytearray(int(pkt.fields['dat_w']), self.bytes_per_line)
                self.mem.write(line, data, int(pkt.fields['sel']))
            else:
                pkt.fields['dat_r'] = self.mem.bytearray_to_integer(
                    self.mem.read(line, self.bytes_per_line))
        return status

    def _drive_term(self, status, dat_r):
        self.bus.ACK.value = int(status == WB4_STATUS_ACK)
        if self.is_signal_present('ERR'):
            self.bus.ERR.value = int(status == WB4_STATUS_ERR)
        if self.is_signal_present('RTY'):
            self.bus.RTY.value = int(status == WB4_STATUS_RTY)
        if status is not None:
            self.bus.DAT_R.value = dat_r

    async def _monitor_recv(self):
        while True:
            await RisingEdge(self.clock)
            self._clock_no += 1
            # ---- drive: one termination this clock if the head is due ----
            terminating = False
            if self._pending and self._pending[0][0] <= self._clock_no and self.outstanding:
                _due, pkt = self._pending.popleft()
                self._drive_term(int(pkt.fields['status']), int(pkt.fields['dat_r']))
                terminating = True
                self.outstanding -= 1
                object.__setattr__(pkt, 'end_time', get_sim_time('ns'))
                self.sentQ.append(pkt)
                self.stats[WB4_STATUS_NAMES[int(pkt.fields['status'])].lower()] += 1
                self.log.debug(f"{self.title} WB4 Slave #{pkt.count}: {pkt.formatted(compact=True)}")
            else:
                self._drive_term(None, 0)
            stall = (self._stall_left > 0) or (self.outstanding >= self.max_outstanding)
            # Classic slaves have no STALL: backpressure is simply not accepting.
            self.bus.STALL.value = 0 if self.classic else int(stall)
            if self._stall_left > 0:
                self._stall_left -= 1

            # ---- sample what the next edge will see ----
            await FallingEdge(self.clock)
            await Timer(_SETTLE_PS, units='ps')
            cyc, stb = _int(self.bus.CYC), _int(self.bus.STB)
            if not cyc:
                if self.outstanding or self._pending:
                    self.stats['aborted'] += self.outstanding
                    self.log.warning(f"{self.title} WB4 Slave: master dropped CYC with "
                                     f"{self.outstanding} outstanding -- aborted")
                self.outstanding = 0
                self._pending.clear()
                continue
            if stb and not stall and not (self.classic and terminating):
                # (classic: `stall` here is the accept gate the master never
                # sees -- a held presentation is accepted exactly once, and
                # not in the clock its termination is being driven)
                self.count += 1
                pkt = WB4Packet(addr_width=self.addr_width, data_width=self.data_width,
                                sel_width=self.sel_width,
                                we=_int(self.bus.WE), adr=_int(self.bus.ADR),
                                dat_w=_int(self.bus.DAT_W), sel=_int(self.bus.SEL),
                                count=self.count, start_time=get_sim_time('ns'))
                rnd = self.randomizer.next()
                self._service(pkt, rnd)
                latency = max(1, int(rnd.get('ack', 1)))
                self._stall_left = int(rnd.get('stall', 0))
                # due at clock N means driven on the rising edge that starts
                # clock N; +1 is the earliest legal (registered) termination.
                self._pending.append((self._clock_no + latency, pkt))
                self.outstanding += 1
                self.stats['accepted'] += 1


class WB4Master(WB4SignalMixin, BusDriver):
    """Wishbone B4 pipelined master.

    Queue requests with :meth:`send` (a :class:`WB4Packet`); the pipeline
    presents them one per clock while the slave does not STALL, holds CYC
    until the last outstanding request terminates, and fills each packet's
    ``status``/``dat_r`` from the termination that pairs with it, in order.
    Completed packets land in :attr:`sentQ` and go to callbacks added with
    :meth:`add_callback`. :meth:`busy_send` waits for that packet's
    termination.

    Randomizer key ``stb``: idle clocks before the next request is presented.
    ``max_outstanding`` bounds the requests in flight (the RTL master's
    equivalent is its response-queue depth). :meth:`abort` drops CYC with
    requests outstanding, to test a slave's abort handling.
    """

    def __init__(self, entity, title, prefix, clock, signals=None,
                 addr_width=32, data_width=32, randomizer=None,
                 max_outstanding=8, classic=False, log=None, **kwargs):
        prefix = prefix.rstrip('_')
        req, opt, aliases = self._resolve(entity, prefix, signals)
        self._signals = {s: aliases.get(s, s) for s in req}
        self._optional_signals = opt
        BusDriver.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        self.title = title
        self.prefix = prefix
        self.log = log or entity._log
        self.addr_width = addr_width
        self.data_width = data_width
        self.sel_width = data_width // 8
        self.randomizer = randomizer or FlexRandomizer(self._default_randomizer_constraints())
        # Classic: hold the request on STB/CYC until its termination, one at a
        # time, and ignore STALL (a classic slave has none).
        self.classic = classic
        self.max_outstanding = 1 if classic else max_outstanding
        self.transmit_queue = deque()
        self.outstanding = deque()
        self.sentQ = deque()
        self.callbacks = []
        self.count = 0
        self.stats = {'sent': 0, 'accepted': 0, 'ack': 0, 'err': 0, 'rty': 0,
                      'unexpected_term': 0, 'max_inflight': 0}
        self.transfer_busy = False
        self._abort = False
        self._hold = False               # queued requests wait until resume()
        self.last_abort = None           # {'outstanding': n, 'head_dropped': bool} after abort()
        self._head = None                # packet currently presented on STB
        self._gap = 0
        for sig in ('CYC', 'STB', 'WE', 'ADR', 'DAT_W', 'SEL'):
            getattr(self.bus, sig).setimmediatevalue(0)
        self._pipeline = cocotb.start_soon(self._run())

    @staticmethod
    def _default_randomizer_constraints():
        return {'stb': ([(0, 0), (1, 3), (4, 8)], [8, 2, 1])}

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer
        self.log.info(f"Set new randomizer for WB4 Master ({self.title})")

    def add_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    async def reset_bus(self):
        self.transmit_queue.clear()
        self.outstanding.clear()
        self._head = None
        self._abort = False
        for sig in ('CYC', 'STB', 'WE', 'ADR', 'DAT_W', 'SEL'):
            getattr(self.bus, sig).value = 0

    def hold(self):
        """Stop presenting queued requests (in-flight ones still terminate)."""
        self._hold = True

    def resume(self):
        self._hold = False

    def abort(self):
        """Drop CYC on the next edge and forget everything outstanding.
        The slave under test must discard those transfers; this master will
        report their late terminations as ``unexpected_term``. After the edge,
        :attr:`last_abort` says how many were outstanding and whether a
        request presented on STB was dropped unaccepted. The queue is HELD
        until :meth:`resume`, so a test can reconcile its bookkeeping before
        the next cycle starts."""
        self._abort = True
        self._hold = True

    def create_packet(self, **fields):
        return WB4Packet(addr_width=self.addr_width, data_width=self.data_width,
                         sel_width=self.sel_width, **fields)

    async def _driver_send(self, transaction, sync=True, hold=False, **kwargs):
        self.transmit_queue.append(transaction)
        self.transfer_busy = True
        self.stats['sent'] += 1

    async def busy_send(self, transaction):
        await self.send(transaction)
        while transaction.end_time == 0:
            await RisingEdge(self.clock)

    async def wait_idle(self):
        while self.transmit_queue or self.outstanding or self._head is not None:
            await RisingEdge(self.clock)

    def _present(self, pkt):
        self.bus.STB.value = 1
        self.bus.WE.value = int(pkt.fields['we'])
        self.bus.ADR.value = int(pkt.fields['adr'])
        self.bus.DAT_W.value = int(pkt.fields['dat_w'])
        self.bus.SEL.value = int(pkt.fields['sel'])

    def _complete(self, pkt, status, dat_r):
        pkt.fields['status'] = status
        pkt.fields['dat_r'] = dat_r
        object.__setattr__(pkt, 'end_time', get_sim_time('ns'))
        self.sentQ.append(pkt)
        self.stats[WB4_STATUS_NAMES[status].lower()] += 1
        for cb in self.callbacks:
            cb(pkt)
        self.log.debug(f"{self.title} WB4 Master #{pkt.count}: {pkt.formatted(compact=True)}")

    async def _run(self):
        accepted = False
        term = None
        while True:
            await RisingEdge(self.clock)
            # ---- bookkeeping for what the edge just sampled ----
            if accepted and self._head is not None:
                self.outstanding.append(self._head)
                self.stats['accepted'] += 1
                self.stats['max_inflight'] = max(self.stats['max_inflight'], len(self.outstanding))
                self._head = None
            if term is not None:
                status, dat_r = term
                if self.outstanding:
                    self._complete(self.outstanding.popleft(), status, dat_r)
                else:
                    self.stats['unexpected_term'] += 1
                    self.log.warning(f"{self.title} WB4 Master: {WB4_STATUS_NAMES[status]} "
                                     f"with nothing outstanding")
            if self._abort:
                # What this abort threw away: the requests the slave had
                # accepted (it must discard their responses) and, if one was
                # on STB, the request it never accepted. Queued requests stay
                # and start a new cycle.
                self.last_abort = {'outstanding': len(self.outstanding),
                                   'head_dropped': self._head is not None}
                self.log.info(f"{self.title} WB4 Master: abort -- {self.last_abort}")
                self.outstanding.clear()
                self._head = None
                self._abort = False
                self.bus.CYC.value = 0
                self.bus.STB.value = 0
                accepted, term = False, None
                await FallingEdge(self.clock)
                continue
            # ---- drive this clock ----
            if self._head is None and self.transmit_queue and self._gap == 0 \
                    and not self._hold and len(self.outstanding) < self.max_outstanding:
                self._head = self.transmit_queue.popleft()
                self.count += 1
                object.__setattr__(self._head, 'count', self.count)
                object.__setattr__(self._head, 'start_time', get_sim_time('ns'))
                self._gap = int(self.randomizer.next().get('stb', 0))
            elif self._head is None and self._gap > 0:
                self._gap -= 1
            if self._head is not None:
                self._present(self._head)
            elif self.classic and self.outstanding:
                self._present(self.outstanding[0])     # held until terminated
            else:
                self.bus.STB.value = 0
            self.bus.CYC.value = int(self._head is not None or len(self.outstanding) > 0)
            self.transfer_busy = bool(self._head is not None or self.outstanding or self.transmit_queue)

            # ---- sample what the next edge will see ----
            await FallingEdge(self.clock)
            await Timer(_SETTLE_PS, units='ps')
            accepted = bool(self._head is not None and (self.classic or not _int(self.bus.STALL)))
            ack, err, rty = self._term_bits()
            st = _status_of(ack, err, rty)
            term = (st, _int(self.bus.DAT_R)) if st is not None else None
