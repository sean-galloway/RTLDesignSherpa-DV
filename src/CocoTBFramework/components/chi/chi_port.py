# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_port
# Purpose: The clocked chassis every CHI BFM runs on: signal binding, the
#          per-channel credited flit links, the LINKACTIVE pair per
#          direction, SACTIVE, and the rising-edge drive / falling-edge
#          sample loop
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI port chassis.

Why this is not a GAXI composition: CHI has no READY. A flit moves when the
transmitter spends an L-Credit the receiver granted on LCRDV, FLITPEND must
be high the cycle before FLITV, and one LINKACTIVEREQ/ACK pair per
direction gates every channel (IHI 0050H B14). So, like the CXS family,
each BFM runs its own clocked loop and shares the framework parts: the
:class:`CHIFlit` packets, ``FlexRandomizer`` timing, and a ``_recvQ`` plus
callbacks. The cycle-level rules live in pure-Python models
(:mod:`chi_link`) so a spec question is answerable without a simulator.

Timing convention (the APB / WB4 / CXS one): outputs change right after the
rising edge; inputs are sampled at the falling edge, so a value sampled in
cycle t is what the step models see at the rising edge of t+1. That is
exactly how the spec's "an L-Credit cannot be used in the same cycle as
being received" (B14.2.1.1) falls out.

Port naming. The spec names signals from the node's own perspective
(TXREQFLITV is what an RN drives), and a DUT names its ports from ITS
perspective. So a BFM, whatever node it plays, drives the DUT's ``rx*``
pins and samples its ``tx*`` pins: the binder asks the shared
:class:`SignalResolver` for the port kind on the far side of the link
(``chi_hn_f_port`` for an RN-F BFM, ``chi_rn_f_port`` for an HN-F BFM) and
swaps tx/rx on every logical name. Nothing in a TB says which side it is
on; ``prefix`` and ``bus_name`` are tried with and without a trailing
underscore over the spellings a port may use (``rxreqflitv``,
``rxreq_flitv``, ``rx_req_flit_v``, ``RXREQFLITV``, ...). ``signal_map``
overrides any subset, keyed by the BFM-perspective name
(``{'txreqflit': 'my_req_bus'}``), and discovery does the rest. A
loopback DUT with no node of its own (``tests/sim/rtl/chi/chi_wires.sv``)
simply names each side's pins the way the node across from it would.

Signals bound, per :class:`CHIConfig` node type: for each TX channel
``tx<ch>flitpend / flitv / flit`` (driven) and ``tx<ch>lcrdv`` (read); for
each RX channel ``rx<ch>flitpend / flitv / flit`` (read) and
``rx<ch>lcrdv`` (driven); ``txlinkactivereq`` (driven), ``txlinkactiveack``
(read), ``rxlinkactivereq`` (read), ``rxlinkactiveack`` (driven);
``txsactive`` (driven), ``rxsactive`` (read). Resource Planes and shared
credits (``*FLITRP``, ``*SHAREDCRD``, ``*LCRDSHV``) are not bound.
"""

from collections import deque
from typing import Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from ..shared.flex_randomizer import FlexRandomizer
from ..shared.signal_mapping_helper import SignalResolver
from .chi_config import CHIConfig, NodeType
from .chi_flits import flit_class
from .chi_link import (
    DEACTIVATE,
    LCRD_RETURN,
    RUN,
    RxChannel,
    RxLink,
    TxChannel,
    TxLink,
    link_state,
)

_X = object()


def _int(sig, default=0):
    if sig is None:
        return default
    try:
        return int(sig.value)
    except (ValueError, TypeError):
        return default


def _int_or_x(sig, default=0):
    """int value, or the :data:`_X` sentinel when the signal holds X/Z."""
    if sig is None:
        return default
    try:
        return int(sig.value)
    except (ValueError, TypeError):
        return _X


def _swap(name: str) -> str:
    if name.startswith('tx'):
        return 'rx' + name[2:]
    if name.startswith('rx'):
        return 'tx' + name[2:]
    return name


# The port kind on the other side of a link (B13.6): what a BFM playing the
# left node sees on the DUT.
_MIRROR = {NodeType.RN_F: 'hn_f', NodeType.RN_D: 'hn_f', NodeType.RN_I: 'hn_i',
           NodeType.HN_F: 'rn_f', NodeType.HN_I: 'rn_i'}


def chi_protocol_type(node_type: NodeType) -> str:
    """The SignalResolver protocol type for a BFM playing ``node_type``: the
    port kind across the link, whose pin names the DUT carries."""
    kind = _MIRROR.get(node_type)
    if kind is None:
        raise ValueError(f"no BFM plays the node across from a {node_type.value} port")
    return f"chi_{kind}_port"


def bind_chi_signals(owner, dut, title, prefix, bus_name, cfg: CHIConfig, signal_map, wanted, log):
    """Resolve ``wanted`` (BFM-perspective names) on ``dut`` through the
    shared resolver; raise naming what was tried for any the config needs."""
    smap = {_swap(k): v for k, v in (signal_map or {}).items()} or None
    resolver = SignalResolver(chi_protocol_type(cfg.node_type), dut, None, log, title,
                              prefix=prefix, bus_name=bus_name, signal_map=smap)
    resolver.get_signal_lists()
    sig, missing = {}, []
    for name in wanted:
        obj = resolver.get_signal(_swap(name))
        if obj is None:
            missing.append(name)
        else:
            sig[name] = obj
    if missing:
        dut_names = {_swap(m) for m in missing}
        tried = {n: sorted(t)[:6] for n, t, _ in resolver.missing_signals if n in dut_names}
        raise AttributeError(f"{title}: CHI signals {missing} (DUT names {sorted(dut_names)}) not found on "
                             f"{dut._name} (prefix '{prefix}', bus_name '{bus_name}', {resolver.protocol_type}); "
                             f"{cfg.short_name()} needs them. Tried e.g. {tried}")
    owner.resolver = resolver
    return sig


class CHIPort:
    """One CHI port: binding, credited channels, link handshake, SACTIVE.

    Subclasses implement :meth:`_on_rx` (a protocol flit arrived on an RX
    channel) and :meth:`_sactive` (TXSACTIVE value, B14.7.2). They send
    with :meth:`send`.

    Randomizer keys (``FlexRandomizer``): ``flit_gap`` idle cycles after
    each TX flit per channel, ``lcrd_gap`` cycles between grants per RX
    channel, ``drain_gap`` cycles the modelled RX buffer holds a flit,
    ``ack_delay`` cycles from seeing LINKACTIVEREQ to raising ACK.
    """

    def __init__(self, dut, title, prefix, clock, cfg: CHIConfig, reset=None, reset_active_low=True,
                 signal_map: Optional[Dict[str, str]] = None, log=None,
                 randomizer=None, auto_link=True, idle_deactivate: Optional[int] = None,
                 rx_buffer_depth: Optional[int] = None, pend_mode='exact', bus_name: str = ''):
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
        self.signal_map = dict(signal_map or {})
        self.randomizer = randomizer or FlexRandomizer(self._default_randomizer_constraints())
        self.violations: Dict[str, int] = {}
        self.stats: Dict[str, int] = {'cycles': 0, 'cycles_run_tx': 0, 'cycles_run_rx': 0}
        self._recvQ = deque()
        self.callbacks: List[Callable] = []
        self.sig = bind_chi_signals(self, dut, title, prefix, bus_name, cfg,
                                    self.signal_map, self._wanted_signals(), self.log)
        # channel and link models
        mc = cfg.max_lcredit
        self.tx: Dict[str, TxChannel] = {
            ch: TxChannel(ch, max_credit=mc, pend_mode=pend_mode) for ch in cfg.tx_channels}
        self.rx: Dict[str, RxChannel] = {
            ch: RxChannel(ch, max_credit=mc, buffer_depth=rx_buffer_depth,
                          grant_gap=lambda: int(self.randomizer.next().get('lcrd_gap', 0)),
                          drain_gap=lambda: int(self.randomizer.next().get('drain_gap', 0)))
            for ch in cfg.rx_channels}
        self.txlink = TxLink(auto=auto_link, idle_deactivate=idle_deactivate)
        self.rxlink = RxLink(ack_delay=lambda: int(self.randomizer.next().get('ack_delay', 0)))
        self._gap: Dict[str, int] = {ch: 0 for ch in cfg.tx_channels}
        # sampled inputs (falling edge) feeding the next rising edge
        self._s_lcrdv: Dict[str, int] = {ch: 0 for ch in cfg.tx_channels}
        self._s_flitv: Dict[str, int] = {ch: 0 for ch in cfg.rx_channels}
        self._s_lcrd_ret: Dict[str, int] = {ch: 0 for ch in cfg.rx_channels}
        self._s_pend: Dict[str, int] = {ch: 0 for ch in cfg.rx_channels}
        self._s_txack = 0
        self._s_rxreq = 0
        self._s_rxsactive = 0
        self.txsactive = 0
        self.count = 0
        self._drive_idle()
        self._task = cocotb.start_soon(self._run())

    @staticmethod
    def _default_randomizer_constraints():
        return {
            'flit_gap': ([(0, 0), (1, 2)], [8, 1]),
            'lcrd_gap': ([(0, 0), (1, 2)], [12, 1]),
            'drain_gap': ([(0, 0), (1, 3)], [10, 1]),
            'ack_delay': ([(0, 0), (1, 4)], [3, 1]),
        }

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer

    # -- binding -----------------------------------------------------------
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

    def has(self, name):
        return name in self.sig

    def sig_read(self, name, default=0):
        return _int(self.sig.get(name), default)

    def sig_read_x(self, name, what=None):
        """Read a control signal; X/Z counts as a ``x_on_wire`` violation and reads 0."""
        v = _int_or_x(self.sig.get(name), 0)
        if v is _X:
            self._violation('x_on_wire', f"{what or name} is X/Z")
            return 0
        return v

    def sig_drive(self, name, value):
        if name in self.sig:
            self.sig[name].value = int(value)

    def in_reset(self):
        if self.reset is None:
            return False
        v = _int(self.reset, 0 if self.reset_active_low else 1)
        return (v == 0) if self.reset_active_low else (v == 1)

    # -- reporting -----------------------------------------------------------
    def _violation(self, kind, msg):
        self.violations[kind] = self.violations.get(kind, 0) + 1
        if self.log:
            self.log.error(f"{self.title} CHI: {msg} @ {get_sim_time('ns')}ns")

    def total_violations(self):
        return sum(self.all_violations().values())

    def all_violations(self):
        out = dict(self.violations)
        for m in list(self.tx.values()) + list(self.rx.values()):
            for k, v in getattr(m, 'violations', {}).items():
                out[f"{m.name}.{k}"] = out.get(f"{m.name}.{k}", 0) + v
        for k, v in getattr(self.txlink, 'violations', {}).items():
            out[f"txlink.{k}"] = out.get(f"txlink.{k}", 0) + v
        return out

    def add_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def _deliver(self, item):
        self._recvQ.append(item)
        for cb in self.callbacks:
            cb(item)

    # -- API ------------------------------------------------------------------
    def send(self, channel: str, flit):
        """Queue a protocol flit on a TX channel. Each flit costs one L-Credit."""
        if channel not in self.tx:
            raise ValueError(f"{self.title}: {self.cfg.node_type.value} has no TX {channel.upper()} channel")
        self.tx[channel].queue.append(flit)

    def have_work(self):
        return any(t.queue for t in self.tx.values())

    @property
    def tx_state(self):
        return link_state(self.txlink.req, self._s_txack) if self.cfg.link_control else RUN

    @property
    def rx_state(self):
        return link_state(self._s_rxreq, self.rxlink.ack) if self.cfg.link_control else RUN

    def activate(self):
        self.txlink.want(True)

    def deactivate(self):
        self.txlink.want(False)

    async def reset_bus(self):
        """House idiom (as ``GAXIMaster.reset_bus``): drop every open link and
        transaction, drive the idle values B14.1.3 requires during reset, and
        return after one clock. Call it from the TB's reset sequence; the
        optional ``reset=`` pin does the same automatically."""
        self._reset_models()
        self._reset_protocol()
        self._drive_idle()
        await RisingEdge(self.clock)

    async def wait_link(self, state, timeout_cycles=10000):
        for _ in range(timeout_cycles):
            if self.tx_state == state and self.rx_state == state:
                return
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: link never reached {state} (tx={self.tx_state} rx={self.rx_state})")

    async def wait_tx_idle(self, timeout_cycles=100000):
        for _ in range(timeout_cycles):
            if not self.have_work():
                return
            await RisingEdge(self.clock)
        raise TimeoutError(f"{self.title}: TX queues not empty "
                           f"({ {ch: len(t.queue) for ch, t in self.tx.items()} }), tx={self.tx_state}")

    # -- hooks for subclasses ---------------------------------------------------
    def _on_rx(self, channel: str, flit):
        """A protocol flit arrived on ``channel``. Default: deliver to the queue."""
        self._deliver(flit)

    def _reset_protocol(self):
        """Reset seen on the wire: drop every open transaction (subclasses)."""

    def _sactive(self) -> int:
        """TXSACTIVE (B14.7.2): asserted while this node has flits to send or
        transactions in progress. Subclasses refine."""
        return int(self.have_work())

    def _lcrd_return_flit(self, channel):
        """B13.11: opcode 0, TxnID 0, other fields any value."""
        return flit_class(channel)(self.cfg, opcode=0, txnid=0)

    # -- loop ---------------------------------------------------------------------
    def _drive_idle(self):
        for ch in self.cfg.tx_channels:
            self.sig_drive(f"tx{ch}flitpend", 0)
            self.sig_drive(f"tx{ch}flitv", 0)
            self.sig_drive(f"tx{ch}flit", 0)
        for ch in self.cfg.rx_channels:
            self.sig_drive(f"rx{ch}lcrdv", 0)
        self.sig_drive('txlinkactivereq', 0)
        self.sig_drive('rxlinkactiveack', 0)
        self.sig_drive('txsactive', 0)

    def _reset_models(self):
        for t in self.tx.values():
            t.reset()
        for r in self.rx.values():
            r.reset()
        self.txlink.reset()
        self.rxlink.reset()
        for d in (self._s_lcrdv, self._s_flitv, self._s_lcrd_ret, self._s_pend, self._gap):
            for k in d:
                d[k] = 0
        self._s_txack = self._s_rxreq = self._s_rxsactive = 0

    async def _run(self):
        cfg = self.cfg
        while True:
            await RisingEdge(self.clock)
            if self.in_reset():
                self._reset_models()
                self._reset_protocol()
                self._drive_idle()
                await FallingEdge(self.clock)
                continue
            self.stats['cycles'] += 1
            # -- link handshakes (one pair per direction) -------------------------
            if cfg.link_control:
                # include what was sampled last cycle and is about to be stepped in
                tx_returned = all(t.all_returned() and not self._s_lcrdv[ch] for ch, t in self.tx.items())
                rx_returned = all(r.credit.outstanding - self._s_lcrd_ret[ch] <= 0 for ch, r in self.rx.items())
                req = self.txlink.step(self._s_txack, self.have_work(), tx_returned, self.rx_state)
                ack = self.rxlink.step(self._s_rxreq, rx_returned, tx_req=req)
                self.sig_drive('txlinkactivereq', req)
                self.sig_drive('rxlinkactiveack', ack)
                tx_state = link_state(req, self._s_txack)
                rx_state = link_state(self._s_rxreq, ack)
            else:
                tx_state = rx_state = RUN
            run_tx, deact_tx = tx_state == RUN, tx_state == DEACTIVATE
            run_rx = rx_state == RUN
            self.stats['cycles_run_tx'] += int(run_tx)
            self.stats['cycles_run_rx'] += int(run_rx)
            # -- TX channels ----------------------------------------------------------
            for ch, t in self.tx.items():
                gap_hold = self._gap[ch] > 0
                pend, v, flit = t.step(run_tx and not gap_hold, deact_tx, self._s_lcrdv[ch])
                if gap_hold:
                    self._gap[ch] -= 1
                word = 0
                if v:
                    if flit is LCRD_RETURN:
                        flit = self._lcrd_return_flit(ch)
                    else:
                        self.count += 1
                        object.__setattr__(flit, 'count', self.count)
                        object.__setattr__(flit, 'start_time', get_sim_time('ns'))
                        self._gap[ch] = int(self.randomizer.next().get('flit_gap', 0))
                    word = flit.pack()
                self.sig_drive(f"tx{ch}flitpend", pend)
                self.sig_drive(f"tx{ch}flitv", v)
                if v:
                    self.sig_drive(f"tx{ch}flit", word)
            # -- RX channels ------------------------------------------------------------
            for ch, r in self.rx.items():
                lcrdv = r.step(run_rx, self._s_flitv[ch], bool(self._s_lcrd_ret[ch]))
                self.sig_drive(f"rx{ch}lcrdv", lcrdv)
            # -- SACTIVE ------------------------------------------------------------------
            self.txsactive = int(self._sactive())
            self.sig_drive('txsactive', self.txsactive)

            # ============ sample ============
            await FallingEdge(self.clock)
            for ch in self.tx:
                self._s_lcrdv[ch] = self.sig_read_x(f"tx{ch}lcrdv")
            for ch in self.rx:
                pend_prev = self._s_pend[ch]
                self._s_pend[ch] = self.sig_read_x(f"rx{ch}flitpend")
                v = self.sig_read_x(f"rx{ch}flitv")
                self._s_flitv[ch] = v
                self._s_lcrd_ret[ch] = 0
                if v:
                    if not pend_prev:
                        self._violation('valid_without_pend',
                                        f"RX{ch.upper()}FLITV without FLITPEND the cycle before (B14.4)")
                    word = _int_or_x(self.sig.get(f"rx{ch}flit"))
                    if word is _X:
                        self._violation('x_on_wire', f"RX{ch.upper()}FLIT has X/Z bits while FLITV is high")
                        continue
                    flit = flit_class(ch).from_word(self.cfg, word)
                    object.__setattr__(flit, 'start_time', get_sim_time('ns'))
                    if flit.is_lcrd_return:
                        self._s_lcrd_ret[ch] = 1
                        if flit.txnid != 0:
                            self._violation('lcrd_return_txnid', f"{ch.upper()} LCrdReturn with TxnID {flit.txnid} != 0 (B13.11)")
                    else:
                        try:
                            self._on_rx(ch, flit)
                        except (ValueError, KeyError) as err:
                            # an opcode or state this family does not model (see the scope list)
                            self._violation('unsupported', f"{ch.upper()} {flit.opcode_name}: {err}")
            if cfg.link_control:
                self._s_txack = self.sig_read_x('txlinkactiveack')
                self._s_rxreq = self.sig_read_x('rxlinkactivereq')
            if cfg.sactive:
                self._s_rxsactive = self.sig_read('rxsactive')

    @property
    def rxsactive(self):
        return self._s_rxsactive


__all__ = ['CHIPort', 'chi_protocol_type', 'bind_chi_signals']
