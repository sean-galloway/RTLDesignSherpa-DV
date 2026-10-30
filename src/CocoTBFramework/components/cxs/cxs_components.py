# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: CXSTransmitter / CXSReceiver / CXSMonitor
# Purpose: CXS (Arm IHI 0079, Issues A-D) BFMs
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""CXS Transmitter, Receiver and Monitor BFMs.

Why these are not GAXI compositions: CXS has no READY. A flit moves when the
transmitter spends a credit; credits move one per cycle on CXSCRDGNT and
back on CXSCRDRTN; and link activation is a four-phase ACTIVEREQ/ACTIVEACK
handshake that gates both. So, like the Wishbone family, each BFM runs its
own clocked loop and shares the framework parts -- ``Packet`` (as
:class:`CXSFlit`), ``FlexRandomizer`` timing, and a ``_recvQ`` plus
callbacks for what it sees.

Timing convention (the APB / WB4 one): outputs change right after the rising
edge; inputs are sampled at the falling edge, i.e. the value the next rising
edge sees. Consequences that match the spec exactly:

* a credit sampled in cycle t is spent in cycle t+1 at the earliest -- "a
  Transmitter cannot use a credit until the cycle after CXSCRDGNT" (2.1.2);
* a credit consumed or returned in cycle t is re-granted in t+1 at the
  earliest -- the receiver reuse rule;
* ACTIVEACK sampled in cycle t lets the transmitter send in t+1.

Ports bind through the shared :class:`SignalResolver` (protocol type
``'cxs'``), like every family: ``prefix`` and ``bus_name`` are tried with
and without a trailing underscore over the spellings a port may use
(``m_cxs_crdgnt``, ``m_cxs_crd_gnt``, ``m_crdgnt``, ``CXSTXCRDGNT`` with
``prefix='CXSTX'``, ...), ``signal_map`` overrides any subset by logical
name (``{'crdgnt': 'odd_pin'}``) and discovery does the rest. Only the
signals the :class:`CXSConfig` says the port has are required of the DUT;
a missing one fails construction naming every spelling that was tried.
"""

import random
from collections import deque
from typing import Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from ..shared.flex_randomizer import FlexRandomizer
from ..shared.signal_mapping_helper import SignalResolver
from .cxs_check import PAYLOAD_SIGNALS, RX_CONTROL_SIGNALS, TX_CONTROL_SIGNALS, odd_parity_chk, signal_width
from .cxs_cntl import CXSCntl
from .cxs_config import CXSConfig
from .cxs_packet import CXSDepacketizer, CXSFlit, CXSPacket, CXSPacketizer

TX_PAYLOAD = PAYLOAD_SIGNALS
TX_DRIVEN = ('valid',) + TX_PAYLOAD + ('crdrtn', 'activereq')
RX_DRIVEN = ('crdgnt', 'activeack', 'deacthint')

# Link states, named by {ACTIVEREQ, ACTIVEACK} (Figure 5-2)
STOP, ACTIVATE, RUN, DEACTIVATE = 'STOP', 'ACTIVATE', 'RUN', 'DEACTIVATE'


def link_state(req, ack):
    return {(0, 0): STOP, (1, 0): ACTIVATE, (1, 1): RUN, (0, 1): DEACTIVATE}[(int(req), int(ack))]


def _int(sig, default=0):
    if sig is None:
        return default
    try:
        return int(sig.value)
    except (ValueError, TypeError):
        return default


class _CXSBase:
    """Signal binding, check-signal arithmetic, reset handling, violations."""

    def __init__(self, dut, title, prefix, clock, cfg: CXSConfig, reset=None,
                 reset_active_low=True, signal_map: Optional[Dict[str, str]] = None, log=None,
                 bus_name: str = ''):
        cfg.validate()
        self.dut = dut
        self.title = title
        self.prefix = prefix
        self.bus_name = bus_name
        self.clock = clock
        self.cfg = cfg
        self.reset = reset
        self.reset_active_low = reset_active_low
        self.log = log or getattr(dut, '_log', None)
        self.violations: Dict[str, int] = {}
        self.signal_map = dict(signal_map or {})
        self.resolver = SignalResolver('cxs', dut, None, self.log, title, prefix=prefix, bus_name=bus_name,
                                       signal_map=self.signal_map or None)
        self.resolver.get_signal_lists()
        self.sig = {}
        missing = []
        for name in self._wanted_signals():
            obj = self.resolver.get_signal(name)
            if obj is None:
                missing.append(name)
            else:
                self.sig[name] = obj
        if missing:
            tried = {n: sorted(t)[:6] for n, t, _ in self.resolver.missing_signals if n in missing}
            raise AttributeError(f"{title}: CXS signals {missing} not found on {dut._name} "
                                 f"(prefix '{prefix}', bus_name '{bus_name}'); the configuration "
                                 f"{cfg.short_name()} needs them. Tried e.g. {tried}")
        self._recvQ = deque()
        self.callbacks: List[Callable] = []

    # -- binding ---------------------------------------------------------
    def _present(self, name):
        """Is ``name`` a signal this interface configuration has?"""
        cfg = self.cfg
        base = name[:-3] if name.endswith('chk') else name
        if name.endswith('chk'):
            if not cfg.check or base == 'deacthint':
                return False
        if base in ('cntl',):
            return cfg.cntl_width > 0
        if base == 'last':
            return cfg.has_last
        if base == 'prcltype':
            return cfg.has_prcltype
        if base in ('srcid', 'tgtid', 'user'):
            return signal_width(cfg, base) > 0
        if base in ('crdrtn', 'activereq', 'activeack', 'deacthint'):
            return cfg.link_control
        return True

    def _wanted_signals(self):
        base = ('valid', 'data', 'cntl', 'last', 'prcltype', 'srcid', 'tgtid', 'user',
                'crdgnt', 'crdrtn', 'activereq', 'activeack', 'deacthint')
        names = list(base) + [f"{b}chk" for b in base if b != 'deacthint']
        return [n for n in names if self._present(n)]

    def has(self, name):
        return name in self.sig

    def read(self, name, default=0):
        return _int(self.sig.get(name), default)

    def drive(self, name, value):
        if name in self.sig:
            self.sig[name].value = int(value)

    # -- reset -----------------------------------------------------------
    def in_reset(self):
        if self.reset is None:
            return False
        v = _int(self.reset, 0 if self.reset_active_low else 1)
        return (v == 0) if self.reset_active_low else (v == 1)

    # -- checks ----------------------------------------------------------
    def chk_value(self, name, value):
        return odd_parity_chk(int(value), max(1, signal_width(self.cfg, name)))

    def _check_received(self, names, enabled):
        """Compare each received check signal against its signal."""
        if not enabled:
            return
        for n in names:
            if self.has(n) and self.has(f"{n}chk"):
                if self.read(f"{n}chk") != self.chk_value(n, self.read(n)):
                    self._violation(f"parity_{n}", f"CXS{n.upper()}CHK mismatch "
                                    f"({n}=0x{self.read(n):X} chk=0x{self.read(n + 'chk'):X})")

    # -- reporting -------------------------------------------------------
    def _violation(self, kind, msg):
        self.violations[kind] = self.violations.get(kind, 0) + 1
        if self.log:
            self.log.error(f"{self.title} CXS protocol: {msg} @ {get_sim_time('ns')}ns")

    def total_violations(self):
        return sum(self.violations.values())

    def add_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def _deliver(self, item):
        self._recvQ.append(item)
        for cb in self.callbacks:
            cb(item)

    def _sample_flit(self, count):
        fields = {'data': self.read('data')}
        for n in ('cntl', 'last', 'prcltype', 'srcid', 'tgtid', 'user'):
            if self.has(n):
                fields[n] = self.read(n)
        f = CXSFlit(self.cfg, count=count, **fields)
        object.__setattr__(f, 'start_time', get_sim_time('ns'))
        return f


# ===========================================================================
# Transmitter
# ===========================================================================
class CXSTransmitter(_CXSBase):
    """Drives the TX side of a CXS link (the DUT is a receiver).

    Queue work with :meth:`send_packet` / :meth:`send_packets` (packed into
    flits by :class:`CXSPacketizer`) or :meth:`send_flit` (raw flits, for
    CXS-Lite and hand-built control words). Each flit spends one credit.

    Link control (``cfg.link_control``): with ``auto_link`` the BFM raises
    CXSACTIVEREQ when it has flits, and drops it when the queue is empty, no
    packet is open, and either CXSDEACTHINT is high or ``idle_deactivate``
    idle RUN cycles have passed (None = only on the hint). While ACTIVEREQ
    is low every credit held is returned on CXSCRDRTN. :meth:`activate` /
    :meth:`deactivate` drive the handshake by hand with ``auto_link=False``.

    Randomizer key ``valid_gap``: idle cycles inserted after each flit.
    :meth:`inject_check_error` corrupts the next N enabled cycles of one
    check signal, to test a receiver's parity checking.
    """

    def __init__(self, dut, title, prefix, clock, cfg: CXSConfig, randomizer=None,
                 auto_link=True, idle_deactivate: Optional[int] = 16, reset=None,
                 reset_active_low=True, signal_map=None, log=None, bus_name=''):
        super().__init__(dut, title, prefix, clock, cfg, reset, reset_active_low, signal_map, log, bus_name)
        self.randomizer = randomizer or FlexRandomizer(self._default_randomizer_constraints())
        self.auto_link = auto_link
        self.idle_deactivate = idle_deactivate
        self.packetizer = CXSPacketizer(cfg)
        self.queue: deque = deque()
        self.sentQ: deque = deque()
        self.credits = 0
        self.req = 0
        self._ack = 0              # sampled CXSACTIVEACK
        self._hint = 0
        self._want_link = False    # manual activate()
        self._idle = 0
        self._gap = 0
        self._in_packet = False
        self._open_streams = set()
        self._chk_inject: Dict[str, int] = {}
        self.count = 0
        self.stats = {'flits': 0, 'credits_received': 0, 'credits_returned': 0,
                      'activations': 0, 'deactivations': 0, 'max_credits': 0,
                      'stall_cycles': 0}
        self._driven: Dict[str, int] = {}
        self._drive_idle()             # check pins start at their idle inversions
        self._task = cocotb.start_soon(self._run())

    @staticmethod
    def _default_randomizer_constraints():
        return {'valid_gap': ([(0, 0), (1, 2), (3, 6)], [10, 2, 1])}

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer

    # -- work ------------------------------------------------------------
    def send_packet(self, pkt: CXSPacket, flush=True):
        """Pack one packet. ``flush=False`` keeps the last flit open so the
        next packet can share it."""
        self.packetizer.add(pkt)
        if flush:
            self.flush()

    def send_packets(self, packets):
        for p in packets:
            self.packetizer.add(p)
        self.flush()

    def flush(self):
        for f in self.packetizer.flush():
            self.send_flit(f)

    def send_flit(self, flit: CXSFlit):
        self.queue.append(flit)

    async def wait_idle(self, timeout_cycles=100000):
        for _ in range(timeout_cycles):
            if not self.queue:
                return
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: {len(self.queue)} flits still queued "
                           f"(credits={self.credits}, link={self.link_state})")

    async def wait_link(self, state, timeout_cycles=10000):
        for _ in range(timeout_cycles):
            if self.link_state == state:
                return
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: link never reached {state} (now {self.link_state})")

    def activate(self):
        self._want_link = True

    def deactivate(self):
        self._want_link = False

    def inject_check_error(self, signal='data', cycles=1):
        self._chk_inject[signal] = self._chk_inject.get(signal, 0) + cycles

    async def reset_bus(self):
        """House idiom (as ``GAXIMaster.reset_bus``): drop credits, link state
        and the open packet, drive the idle values, return after one clock.
        The optional ``reset=`` pin does the same automatically."""
        self.credits, self.req, self._ack, self._in_packet = 0, 0, 0, False
        self._open_streams = set()
        self._driven = {}
        self._drive_idle()
        await RisingEdge(self.clock)

    @property
    def link_state(self):
        return link_state(self.req, self._ack) if self.cfg.link_control else RUN

    # -- loop ------------------------------------------------------------
    def _drive_idle(self):
        for n in TX_DRIVEN:
            self.drive(n, 0)
        self._drive_checks(valid=0)

    def _drive_checks(self, valid):
        if not self.cfg.check:
            return
        for n in TX_DRIVEN:
            if self.has(n) and self.has(f"{n}chk"):
                v = self.chk_value(n, self.read_driven(n))
                enabled = (n in TX_CONTROL_SIGNALS) or valid
                if enabled and self._chk_inject.get(n, 0) > 0:
                    v ^= 1
                    self._chk_inject[n] -= 1
                self.drive(f"{n}chk", v)

    def read_driven(self, n):
        return self._driven.get(n, 0)

    def _decide_link(self):
        cfg = self.cfg
        if not cfg.link_control:
            return
        want = bool(self.queue) or self._want_link
        state = link_state(self.req, self._ack)
        if state == STOP and (want if self.auto_link else self._want_link):
            self.req = 1
            self.stats['activations'] += 1
        elif state == RUN and not self._in_packet and not self.queue:
            if self.auto_link:
                go = self._hint or (self.idle_deactivate is not None
                                    and self._idle >= self.idle_deactivate)
                go = go and not self._want_link
            else:
                go = not self._want_link
            if go:
                self.req = 0
                self.stats['deactivations'] += 1

    async def _run(self):
        cfg = self.cfg
        grant = 0
        while True:
            await RisingEdge(self.clock)
            if self.in_reset():
                self.credits, self.req, self._ack, self._in_packet = 0, 0, 0, False
                self._open_streams = set()
                self._driven = {}
                self._drive_idle()
                await FallingEdge(self.clock)
                grant = 0
                continue
            # credit sampled last cycle is usable now
            if grant:
                self.credits += 1
                self.stats['credits_received'] += 1
                if self.credits > cfg.max_credit:
                    self._violation('credit_overflow',
                                    f"holding {self.credits} credits > CXS_MAX_CREDIT {cfg.max_credit}")
            self.stats['max_credits'] = max(self.stats['max_credits'], self.credits)
            self._decide_link()
            run = (not cfg.link_control) or (self.req and self._ack)
            driven = {n: 0 for n in TX_DRIVEN}
            driven['activereq'] = self.req
            if self._gap > 0:
                self._gap -= 1
            elif run and self.queue and self.credits > 0:
                flit = self.queue.popleft()
                self.credits -= 1
                self.count += 1
                object.__setattr__(flit, 'count', self.count)
                object.__setattr__(flit, 'start_time', get_sim_time('ns'))
                driven['valid'] = 1
                for n in TX_PAYLOAD:
                    if n in flit.fields:
                        driven[n] = flit.get(n)
                self._track_packet(flit)
                self.sentQ.append(flit)
                self.stats['flits'] += 1
                self._gap = int(self.randomizer.next().get('valid_gap', 0))
                self._idle = 0
            elif run and self.queue:
                self.stats['stall_cycles'] += 1
            if cfg.link_control and not self.req and self.credits > 0:
                driven['crdrtn'] = 1
                self.credits -= 1
                self.stats['credits_returned'] += 1
            if run and not self.queue:
                self._idle += 1
            self._driven = driven
            for n, v in driven.items():
                self.drive(n, v)
            self._drive_checks(driven['valid'])

            await FallingEdge(self.clock)
            grant = self.read('crdgnt')
            self._ack = self.read('activeack')
            self._hint = self.read('deacthint')
            self._check_received(RX_CONTROL_SIGNALS, True)

    def _track_packet(self, flit):
        if self.cfg.is_lite:
            return
        # per stream (2.5.2): a packet of another stream does not close this one
        c = flit.control
        stream = (flit.get('prcltype'), flit.get('srcid'), flit.get('tgtid'))
        opens = int(stream in self._open_streams) + len(c.starts) - len(c.ends)
        if opens > 0:
            self._open_streams.add(stream)
        else:
            self._open_streams.discard(stream)
        self._in_packet = bool(self._open_streams)


# ===========================================================================
# Receiver
# ===========================================================================
class CXSReceiver(_CXSBase):
    """Drives the RX side of a CXS link (the DUT is a transmitter).

    Models a receive buffer of ``buffer_depth`` flits (default
    CXS_MAX_CREDIT): a credit is granted only while
    ``buffered + outstanding < buffer_depth`` and ``outstanding <
    CXS_MAX_CREDIT``, so every credit is backed by a slot (2.1.2). The
    buffer drains one flit per cycle, delayed by randomizer key ``drain_gap``
    (models a slow consumer; credits then run out and the transmitter
    stalls). Key ``grant_gap`` spaces grants; ``ack_delay`` is the cycles
    from seeing ACTIVEREQ to raising ACTIVEACK.

    Received flits go to :attr:`_recvQ` / callbacks; complete packets to
    :attr:`packets` (via :class:`CXSDepacketizer`). Link control: ACK rises
    when ACTIVEREQ is seen (if :attr:`rx_enable`), grants only in RUN, and
    ACK falls once every credit is home after ACTIVEREQ drops.
    :meth:`set_deact_hint` drives CXSDEACTHINT.
    """

    def __init__(self, dut, title, prefix, clock, cfg: CXSConfig, buffer_depth=None,
                 randomizer=None, reset=None, reset_active_low=True, signal_map=None,
                 log=None, packet_callback: Optional[Callable] = None, bus_name=''):
        super().__init__(dut, title, prefix, clock, cfg, reset, reset_active_low, signal_map, log, bus_name)
        self.buffer_depth = buffer_depth or cfg.max_credit
        self.randomizer = randomizer or FlexRandomizer(self._default_randomizer_constraints())
        self.depacketizer = CXSDepacketizer(cfg, callback=packet_callback)
        self.rx_enable = True
        self.outstanding = 0
        self.buffered = 0
        self.ack = 0
        self._req = 0
        self._hint = 0
        self._ack_wait = None
        self._grant_gap = 0
        self._drain_gap = 0
        self._chk_inject: Dict[str, int] = {}
        self.count = 0
        self.stats = {'flits': 0, 'credits_granted': 0, 'credits_returned': 0,
                      'max_outstanding': 0, 'grant_blocked_full': 0}
        for n in ('crdgnt', 'activeack', 'deacthint', 'crdgntchk', 'activeackchk'):
            if self.has(n):
                self.sig[n].value = 1 if (n.endswith('chk') and cfg.check) else 0
        self._task = cocotb.start_soon(self._run())

    @staticmethod
    def _default_randomizer_constraints():
        return {
            'grant_gap': ([(0, 0), (1, 2)], [12, 1]),
            'drain_gap': ([(0, 0), (1, 3), (4, 10)], [10, 2, 1]),
            'ack_delay': ([(0, 0), (1, 4)], [3, 1]),
        }

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer

    def set_deact_hint(self, value=True):
        self._hint = int(bool(value))

    def inject_check_error(self, signal='crdgnt', cycles=1):
        """Drive a wrong CXS{signal}CHK (crdgnt or activeack) for ``cycles``
        cycles, to test a transmitter's parity checking."""
        self._chk_inject[signal] = self._chk_inject.get(signal, 0) + cycles

    def _chk_out(self, name, value):
        chk = value ^ 1
        if self._chk_inject.get(name, 0) > 0:
            self._chk_inject[name] -= 1
            chk ^= 1
        return chk

    @property
    def packets(self):
        return self.depacketizer.packets

    async def reset_bus(self):
        """House idiom: forget outstanding credits and the link, drive the idle
        values (check pins at their idle inversions), return after one clock."""
        self.outstanding, self.buffered, self.ack, self._req = 0, 0, 0, 0
        self._ack_wait = None
        for n in ('crdgnt', 'activeack', 'deacthint'):
            self.drive(n, 0)
        if self.cfg.check:
            self.drive('crdgntchk', 1)
            self.drive('activeackchk', 1)
        await RisingEdge(self.clock)

    @property
    def link_state(self):
        return link_state(self._req, self.ack) if self.cfg.link_control else RUN

    async def wait_flits(self, n, timeout_cycles=100000):
        for _ in range(timeout_cycles):
            if self.stats['flits'] >= n:
                return
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: {self.stats['flits']} of {n} flits received")

    async def _run(self):
        cfg = self.cfg
        while True:
            await RisingEdge(self.clock)
            if self.in_reset():
                self.outstanding, self.buffered, self.ack, self._req = 0, 0, 0, 0
                self._ack_wait = None
                for n in ('crdgnt', 'activeack', 'deacthint'):
                    self.drive(n, 0)
                if cfg.check:
                    self.drive('crdgntchk', 1)
                    self.drive('activeackchk', 1)
                await FallingEdge(self.clock)
                continue
            # drain the modelled buffer
            if self.buffered:
                if self._drain_gap > 0:
                    self._drain_gap -= 1
                else:
                    self.buffered -= 1
                    self._drain_gap = int(self.randomizer.next().get('drain_gap', 0))
            # link
            if cfg.link_control:
                if self._req and not self.ack and self.rx_enable:
                    if self._ack_wait is None:
                        self._ack_wait = int(self.randomizer.next().get('ack_delay', 0))
                    if self._ack_wait <= 0:
                        self.ack, self._ack_wait = 1, None
                    else:
                        self._ack_wait -= 1
                elif not self._req and self.ack and self.outstanding == 0:
                    self.ack = 0
                grant_ok = bool(self._req and self.ack)
            else:
                grant_ok = self.rx_enable
            # grant
            grant = 0
            if self._grant_gap > 0:
                self._grant_gap -= 1
            elif grant_ok and self.outstanding < cfg.max_credit:
                if self.buffered + self.outstanding < self.buffer_depth:
                    grant = 1
                    self.outstanding += 1
                    self.stats['credits_granted'] += 1
                    self.stats['max_outstanding'] = max(self.stats['max_outstanding'], self.outstanding)
                    self._grant_gap = int(self.randomizer.next().get('grant_gap', 0))
                else:
                    self.stats['grant_blocked_full'] += 1
            self.drive('crdgnt', grant)
            self.drive('activeack', self.ack)
            self.drive('deacthint', self._hint)
            if cfg.check:
                self.drive('crdgntchk', self._chk_out('crdgnt', grant))
                self.drive('activeackchk', self._chk_out('activeack', self.ack))

            await FallingEdge(self.clock)
            valid, rtn = self.read('valid'), self.read('crdrtn')
            self._req = self.read('activereq')
            self._check_received(TX_CONTROL_SIGNALS, True)
            if valid:
                self._check_received(PAYLOAD_SIGNALS, True)
                if self.outstanding == 0:
                    self._violation('valid_without_credit', "CXSVALID with no credit outstanding")
                self.outstanding = max(0, self.outstanding - 1)
                self.buffered += 1
                self.count += 1
                flit = self._sample_flit(self.count)
                self.stats['flits'] += 1
                self.depacketizer.push(flit)
                self._deliver(flit)
            if rtn:
                if self.outstanding == 0:
                    self._violation('return_without_credit', "CXSCRDRTN with no credit outstanding")
                self.outstanding = max(0, self.outstanding - 1)
                self.stats['credits_returned'] += 1
            if valid and rtn:
                self._violation('valid_with_crdrtn', "CXSVALID and CXSCRDRTN in the same cycle")


# ===========================================================================
# Monitor
# ===========================================================================
class CXSMonitor(_CXSBase):
    """Passive CXS monitor and protocol checker.

    Emits every flit (:attr:`_recvQ`, callbacks) and every reassembled packet
    (:attr:`packets`). Models the transmitter's credit count from the wires
    and checks, counting each kind in :attr:`violations` (logged, never
    raised -- a test decides how loud to be):

    * ``valid_without_credit`` -- a flit with no usable credit (a credit is
      usable the cycle after its grant)
    * ``valid_with_crdrtn`` / ``return_without_credit`` / ``credit_overflow``
    * link: ``valid_not_run`` (a flit outside RUN), ``credit_not_permitted``
      (a grant in STOP or ACTIVATE), ``handshake`` (a 4-phase step out of
      order), ``ack_drop_with_credits`` (ACK fell while the transmitter held
      credits)
    * ``deactivate_in_packet`` -- with CXSCONTINUOUSDATA, ACTIVEREQ fell
      while a packet was open (6.1)
    * ``cntl`` -- a CXSCNTL / placement rule (CXSDepacketizer), and
      ``parity_<signal>`` with CXSCHECKTYPE = Odd_Byte_Parity

    ``in_packet`` and ``tx_credits`` are the live model, ``link_state`` the
    wire state, ``max_credits`` the peak credit count seen (how a test proves
    the credit pool was exercised).
    """

    def __init__(self, dut, title, prefix, clock, cfg: CXSConfig, reset=None,
                 reset_active_low=True, signal_map=None, log=None,
                 packet_callback: Optional[Callable] = None, bus_name=''):
        super().__init__(dut, title, prefix, clock, cfg, reset, reset_active_low, signal_map, log, bus_name)
        self.depacketizer = CXSDepacketizer(cfg, callback=packet_callback)
        self.tx_credits = 0
        self.max_credits = 0
        self.count = 0
        self.req = 0
        self.ack = 0
        self.stats = {'flits': 0, 'grants': 0, 'returns': 0, 'activations': 0,
                      'deactivations': 0, 'cycles_run': 0}
        self._reported = 0
        self._task = cocotb.start_soon(self._run())

    @property
    def packets(self):
        return self.depacketizer.packets

    @property
    def in_packet(self):
        return self.depacketizer.in_packet

    @property
    def link_state(self):
        return link_state(self.req, self.ack) if self.cfg.link_control else RUN

    async def _run(self):
        cfg = self.cfg
        while True:
            await FallingEdge(self.clock)
            if self.in_reset():
                self.tx_credits, self.req, self.ack = 0, 0, 0
                continue
            valid, grant = self.read('valid'), self.read('crdgnt')
            rtn = self.read('crdrtn') if cfg.link_control else 0
            req = self.read('activereq') if cfg.link_control else 1
            ack = self.read('activeack') if cfg.link_control else 1
            if cfg.link_control:
                self._check_link(req, ack, valid, grant)
            self.req, self.ack = req, ack
            if req and ack:
                self.stats['cycles_run'] += 1
            # credits: this cycle's grant is usable next cycle
            if valid and self.tx_credits == 0:
                self._violation('valid_without_credit', "CXSVALID with no usable credit")
            if rtn and self.tx_credits - valid <= 0:
                self._violation('return_without_credit', "CXSCRDRTN with no credit held")
            if valid and rtn:
                self._violation('valid_with_crdrtn', "CXSVALID and CXSCRDRTN in the same cycle")
            self.tx_credits = max(0, self.tx_credits - valid - rtn) + grant
            if self.tx_credits > cfg.max_credit:
                self._violation('credit_overflow',
                                f"{self.tx_credits} credits granted > CXS_MAX_CREDIT {cfg.max_credit}")
            self.max_credits = max(self.max_credits, self.tx_credits)
            self.stats['grants'] += grant
            self.stats['returns'] += rtn
            self._check_received(TX_CONTROL_SIGNALS + RX_CONTROL_SIGNALS, True)
            if valid:
                self._check_received(PAYLOAD_SIGNALS, True)
                self.count += 1
                self.stats['flits'] += 1
                flit = self._sample_flit(self.count)
                self.depacketizer.push(flit)
                for v in self.depacketizer.violations[self._reported:]:
                    self._violation('cntl', v)
                self._reported = len(self.depacketizer.violations)
                self._deliver(flit)

    def _check_link(self, req, ack, valid, grant):
        pr, pa = self.req, self.ack
        if req != pr:
            if req and pa:
                self._violation('handshake', "ACTIVEREQ rose while ACTIVEACK still high")
            if not req and not pa:
                self._violation('handshake', "ACTIVEREQ fell in ACTIVATE (before ACTIVEACK)")
            self.stats['activations' if req else 'deactivations'] += 1
            if not req and self.cfg.continuous and self.in_packet:
                self._violation('deactivate_in_packet',
                                "ACTIVEREQ fell with a packet open (CXSCONTINUOUSDATA, 6.1)")
        if ack != pa:
            if ack and not pr:
                self._violation('handshake', "ACTIVEACK rose without ACTIVEREQ")
            if not ack and pr:
                self._violation('handshake', "ACTIVEACK fell while ACTIVEREQ high")
            if not ack and self.tx_credits:
                self._violation('ack_drop_with_credits',
                                f"ACTIVEACK fell with {self.tx_credits} credits at the transmitter")
        if valid and not (req and ack):
            self._violation('valid_not_run', f"CXSVALID in {link_state(req, ack)}")
        if grant and not ack:
            self._violation('credit_not_permitted', f"CXSCRDGNT in {link_state(req, ack)}")


def random_packet(cfg: CXSConfig, rng: random.Random, min_bytes=4, max_bytes=None,
                  streams=None, end_error_rate=0.0, keep_rate=0.0) -> CXSPacket:
    """A random legal packet for ``cfg`` (CXS-Lite: exactly one flit)."""
    if cfg.is_lite:
        size = cfg.flit_bytes
    else:
        max_bytes = max_bytes or 3 * cfg.flit_bytes
        size = 4 * rng.randint(max(1, min_bytes // 4), max(1, max_bytes // 4))
    prcl, src, tgt = (rng.choice(streams) if streams else (0, 0, 0))
    # CXS-Lite has no CXSCNTL (no ENDERROR) and no CXSLAST
    lite = cfg.is_lite
    return CXSPacket(bytes(rng.getrandbits(8) for _ in range(size)), prcltype=prcl,
                     srcid=src, tgtid=tgt, end_error=not lite and rng.random() < end_error_rate,
                     keep_with_next=not lite and rng.random() < keep_rate)


__all__ = ['CXSTransmitter', 'CXSReceiver', 'CXSMonitor', 'random_packet', 'link_state',
           'STOP', 'ACTIVATE', 'RUN', 'DEACTIVATE', 'CXSCntl']
