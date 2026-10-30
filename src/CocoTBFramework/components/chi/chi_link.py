# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_link
# Purpose: CHI link layer (IHI 0050H chapter B14) as pure-Python per-cycle
#          models: L-Credits, FLITPEND, LCrdReturn, LINKACTIVE, SACTIVE and
#          a passive checker
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI link layer models (IHI 0050H chapter B14).

Pure Python, no cocotb: each class is a per-cycle state machine that the
CHI BFMs step once per clock. The cocotb wrappers (:mod:`chi_port`,
:mod:`chi_monitor`) own the pins; these own the rules, so every rule is
unit-testable without a simulator and the same objects serve a driver, a
responder and a passive monitor.

Timing convention (the CXS / APB / WB4 one): outputs change right after
the rising edge, inputs are sampled at the falling edge. A ``step()`` runs
at the rising edge of cycle n and receives the inputs sampled at the end
of cycle n-1; what it returns is driven during cycle n. Consequences,
each matching a spec rule:

* LCRDV asserted in cycle n is sampled at the end of n and usable in n+1:
  "An L-Credit cannot be used in the same cycle as being received"
  (B14.2.1.1; Figure B14.1 has LCRDV in cycle 1 and FLITV in cycle 2).
* FLITPEND driven in cycle n permits FLITV in n+1 and nothing else does
  (B14.4).
* ACK sampled at the end of cycle n puts the link in RUN in n+1.

Credits are per channel (B14.5.1.3: a credit is only associated with a
flit on the same channel); the LINKACTIVEREQ/ACK pair is per direction
and its rules apply across every channel of that direction. No Resource
Planes (``Num_RP_* = 1``). During reset every output here is deasserted
(B14.1.3): ``reset()`` on each model returns it to that state.
"""

from collections import deque
from typing import Callable, Dict, Optional

STOP, ACTIVATE, RUN, DEACTIVATE = 'STOP', 'ACTIVATE', 'RUN', 'DEACTIVATE'

#: The flit a :class:`TxChannel` returns when it sends an LCrdReturn. The
#: wrapper builds the real opcode-0, TxnID-0 Link flit (B13.11) for the
#: channel; the model only knows a credit went back.
LCRD_RETURN = object()

MAX_LCREDIT = 15     # B14.2.1.1: a Receiver provides 1..15 credits per channel


def link_state(req, ack) -> str:
    """B14.5 Table B14.1: the four-phase state from (LINKACTIVEREQ, LINKACTIVEACK)."""
    return {(0, 0): STOP, (1, 0): ACTIVATE, (1, 1): RUN, (0, 1): DEACTIVATE}[(int(req), int(ack))]


def _count(d: Dict[str, int], kind: str) -> None:
    d[kind] = d.get(kind, 0) + 1


def _gap(fn: Optional[Callable[[], int]]) -> int:
    return 0 if fn is None else max(0, int(fn()))


# ===========================================================================
# L-Credits (B14.2.1.1)
# ===========================================================================
class LCreditTx:
    """Transmitter-side L-Credit pool for ONE channel (B14.2.1.1).

    :meth:`on_lcrdv` records the LCRDV value seen this cycle into
    ``pending``; :meth:`tick` moves ``pending`` into ``credits`` at the
    start of the next cycle, so a credit received in cycle n is usable in
    n+1 and never in n ("An L-Credit cannot be used in the same cycle as
    being received"). :meth:`spend` pays for one flit, protocol or
    LCrdReturn alike: every flit consumes one credit (B13.11). A pool
    above ``max_credit`` means the receiver granted more than it said it
    would and is counted in ``violations['credit_overflow']``; the count
    is not clamped, so the excess stays visible.

    ``violations`` and ``stats`` survive :meth:`reset`; only the pool
    itself is cleared.
    """

    def __init__(self, max_credit: int = MAX_LCREDIT):
        if not 1 <= int(max_credit) <= MAX_LCREDIT:
            raise ValueError(f"max_credit must be 1..{MAX_LCREDIT} (B14.2.1.1), got {max_credit}")
        self.max_credit = int(max_credit)
        self.credits = 0          # usable now
        self.pending = 0          # seen this cycle, usable next cycle
        self.violations: Dict[str, int] = {}
        self.stats = {'credits_received': 0, 'credits_spent': 0, 'credits_returned': 0, 'max_credits': 0}

    def reset(self) -> None:
        self.credits = 0
        self.pending = 0

    def on_lcrdv(self, lcrdv) -> None:
        """Sample LCRDV for this cycle (0/1)."""
        if int(lcrdv):
            self.pending += 1
            self.stats['credits_received'] += 1

    def tick(self) -> None:
        """Start of a cycle: last cycle's grants become usable. Call once per
        cycle, BEFORE deciding whether to send."""
        self.credits += self.pending
        self.pending = 0
        if self.credits > self.max_credit:
            _count(self.violations, 'credit_overflow')
        self.stats['max_credits'] = max(self.stats['max_credits'], self.credits)

    @property
    def held(self) -> int:
        """Credits at the transmitter, usable or not."""
        return self.credits + self.pending

    def can_send(self) -> bool:
        return self.credits > 0

    def spend(self, lcrd_return: bool = False) -> None:
        """One flit sent (protocol, or an LCrdReturn when ``lcrd_return``)."""
        if self.credits <= 0:
            raise RuntimeError("LCreditTx.spend() with no usable credit (check can_send() first)")
        self.credits -= 1
        self.stats['credits_spent'] += 1
        if lcrd_return:
            self.stats['credits_returned'] += 1


class LCreditRx:
    """Receiver-side credit bookkeeping for ONE channel, slot-backed.

    B14.2.1.1: "a Receiver must be able to accept every flit it has
    granted", so a credit is only granted while a buffer slot backs it:
    :meth:`grant_ok` is ``outstanding < max_credit`` and
    ``buffered + outstanding < buffer_depth`` (``buffer_depth`` defaults to
    ``max_credit``). Each FLITV takes one outstanding credit back
    (:meth:`on_flit`); a protocol flit also occupies a slot until the
    consumer :meth:`drain`\\ s it, an LCrdReturn (B13.11) does not.
    """

    def __init__(self, max_credit: int = MAX_LCREDIT, buffer_depth: Optional[int] = None):
        if not 1 <= int(max_credit) <= MAX_LCREDIT:
            raise ValueError(f"max_credit must be 1..{MAX_LCREDIT} (B14.2.1.1), got {max_credit}")
        self.max_credit = int(max_credit)
        self.buffer_depth = int(buffer_depth) if buffer_depth is not None else self.max_credit
        if self.buffer_depth < 1:
            raise ValueError(f"buffer_depth must be >= 1, got {buffer_depth}")
        self.outstanding = 0      # granted, flit not yet seen
        self.buffered = 0         # protocol flits held for the consumer
        self.violations: Dict[str, int] = {}
        self.stats = {'credits_granted': 0, 'flits': 0, 'lcrd_returns': 0, 'max_outstanding': 0}

    def reset(self) -> None:
        self.outstanding = 0
        self.buffered = 0

    def grant_ok(self) -> bool:
        return self.outstanding < self.max_credit and self.buffered + self.outstanding < self.buffer_depth

    def grant(self) -> None:
        """LCRDV this cycle."""
        if not self.grant_ok():
            raise RuntimeError(f"LCreditRx.grant() beyond the slot-backed limit (outstanding={self.outstanding} "
                               f"buffered={self.buffered} max={self.max_credit} depth={self.buffer_depth})")
        self.outstanding += 1
        self.stats['credits_granted'] += 1
        self.stats['max_outstanding'] = max(self.stats['max_outstanding'], self.outstanding)

    def on_flit(self, is_lcrd_return: bool) -> None:
        """FLITV seen: one credit comes home; a protocol flit takes a slot."""
        if self.outstanding == 0:
            _count(self.violations, 'valid_without_credit')
        else:
            self.outstanding -= 1
        if is_lcrd_return:
            self.stats['lcrd_returns'] += 1
        else:
            self.buffered += 1
            self.stats['flits'] += 1

    def drain(self, n: int = 1) -> None:
        """The consumer took ``n`` buffered flits."""
        self.buffered = max(0, self.buffered - int(n))

    def all_returned(self) -> bool:
        return self.outstanding == 0


# ===========================================================================
# Channels
# ===========================================================================
class TxChannel:
    """Per-cycle driver model for one TX channel: a queue of flits, an
    :class:`LCreditTx`, and FLITPEND one cycle ahead (B14.4).

    ``pend_mode``: ``'exact'`` asserts FLITPEND only while something could
    go next cycle (a queued flit, or the link is deactivating and credits
    may need returning); ``'always'`` holds it permanently asserted. B14.4
    permits both: when asserted the transmitter may or may not send next
    cycle, it may be asserted without a credit, and when deasserted the
    transmitter must NOT send next cycle. A ``pend=`` override on
    :meth:`step` scripts it for one cycle (how a test reproduces a figure).

    ``credit_count`` is the credits usable in the cycle just stepped: what
    a hardware credit counter shows during that cycle, Figure B14.1's
    "Credit count" row. ``credit.credits`` after the step is what is left
    once this cycle's flit (if any) has been paid for.
    """

    def __init__(self, name: str, max_credit: int = MAX_LCREDIT, pend_mode: str = 'exact'):
        if pend_mode not in ('exact', 'always'):
            raise ValueError(f"pend_mode must be 'exact' or 'always', got {pend_mode!r}")
        self.name = name
        self.pend_mode = pend_mode
        self.queue: deque = deque()
        self.credit = LCreditTx(max_credit)
        self.flitpend = 0                 # driven last step; permits a flit this step
        self.credit_count = 0
        self.stats = {'flits': 0, 'lcrd_returns': 0, 'stall_cycles': 0}

    def reset(self) -> None:
        """B14.1.3: FLITV and FLITPEND deasserted in reset; the pool is empty.
        Queued flits are kept, they go once the link is up again."""
        self.credit.reset()
        self.flitpend = 0
        self.credit_count = 0

    @property
    def violations(self) -> Dict[str, int]:
        return self.credit.violations

    def all_returned(self) -> bool:
        """No credit at the transmitter, usable or pending (the queue is
        irrelevant: unsent protocol flits wait for the next activation)."""
        return self.credit.held == 0

    def step(self, run: bool, deactivating: bool, lcrdv, pend: Optional[int] = None):
        """Advance one cycle; returns ``(flitpend, flitv, flit)``.

        ``lcrdv`` is the value sampled on this channel's LCRDV at the end of
        the PREVIOUS cycle; it becomes usable now (B14.2.1.1). ``flitv`` is
        1 only if the previous step drove ``flitpend`` = 1 (B14.4). In RUN
        with a usable credit and a queued flit the flit goes. In DEACTIVATE
        (``deactivating``) with a credit held an LCrdReturn goes instead
        (``flit`` is :data:`LCRD_RETURN`); B14.5 Table B14.2: the
        transmitter returns every unused credit and keeps accepting and
        returning credits that arrive meanwhile. In STOP or ACTIVATE nothing
        is sent, but credits are still accepted (the ACK-and-credit
        same-cycle race of Table B14.2). ``pend`` overrides this cycle's
        FLITPEND.
        """
        self.credit.on_lcrdv(lcrdv)
        self.credit.tick()
        self.credit_count = self.credit.credits
        flitv, flit = 0, None
        if self.flitpend and self.credit.can_send():
            if run and self.queue:
                flit = self.queue.popleft()
                self.credit.spend()
                flitv = 1
                self.stats['flits'] += 1
            elif deactivating:
                flit = LCRD_RETURN
                self.credit.spend(lcrd_return=True)
                flitv = 1
                self.stats['lcrd_returns'] += 1
        if run and self.queue and not flitv:
            self.stats['stall_cycles'] += 1
        if pend is not None:
            self.flitpend = int(bool(pend))
        elif self.pend_mode == 'always':
            self.flitpend = 1
        else:
            self.flitpend = int(bool(self.queue) or deactivating)
        return self.flitpend, flitv, flit


class RxChannel:
    """Per-cycle receiver model for one RX channel.

    Grants one credit per cycle in RUN while :class:`LCreditRx` has a slot
    to back it, spaced by ``grant_gap`` (a callable returning idle cycles
    after a grant; None = 0). The modelled buffer drains one protocol flit
    per cycle, each held ``drain_gap`` extra cycles (a slow consumer:
    credits then run out and the transmitter stalls, which is how a test
    exercises back-pressure).
    """

    def __init__(self, name: str, max_credit: int = MAX_LCREDIT, buffer_depth: Optional[int] = None,
                 grant_gap: Optional[Callable[[], int]] = None, drain_gap: Optional[Callable[[], int]] = None):
        self.name = name
        self.credit = LCreditRx(max_credit, buffer_depth)
        self._grant_gap = grant_gap
        self._drain_gap = drain_gap
        self._grant_wait = 0
        self._drain_wait = 0
        self.lcrdv = 0
        self.stats = {'grants': 0, 'grant_blocked': 0, 'flits': 0, 'lcrd_returns': 0}

    def reset(self) -> None:
        """B14.1.3: LCRDV deasserted in reset; nothing granted or buffered."""
        self.credit.reset()
        self._grant_wait = 0
        self._drain_wait = 0
        self.lcrdv = 0

    @property
    def violations(self) -> Dict[str, int]:
        return self.credit.violations

    def step(self, run: bool, flitv, is_lcrd_return: bool) -> int:
        """Advance one cycle: account the flit sampled at the end of the
        previous cycle (if ``flitv``), drain the modelled buffer, and return
        LCRDV for this cycle: 1 only when ``run``, a slot backs the credit,
        and no grant gap is pending. Credits are sent in RUN only (B14.5
        Table B14.3); the cycle a REQ drop has not yet been sampled is the
        "may send some when first entering DEACTIVATE" allowance."""
        if int(flitv):
            self.credit.on_flit(bool(is_lcrd_return))
            self.stats['lcrd_returns' if is_lcrd_return else 'flits'] += 1
        if self.credit.buffered:
            if self._drain_wait > 0:
                self._drain_wait -= 1
            else:
                self.credit.drain(1)
                self._drain_wait = _gap(self._drain_gap)
        lcrdv = 0
        if self._grant_wait > 0:
            self._grant_wait -= 1
        elif run:
            if self.credit.grant_ok():
                self.credit.grant()
                lcrdv = 1
                self.stats['grants'] += 1
                self._grant_wait = _gap(self._grant_gap)
            else:
                self.stats['grant_blocked'] += 1
        self.lcrdv = lcrdv
        return lcrdv


# ===========================================================================
# Link activation (B14.5, B14.6)
# ===========================================================================
class TxLink:
    """LINKACTIVEREQ controller for the TX direction (all TX channels).

    ``auto``: raise REQ when there is work and drop it after
    ``idle_deactivate`` idle RUN cycles (None = never on idleness). With
    ``auto=False`` only :meth:`want` moves it. Either way the link follows
    the remote (B14.6): when the RX link is activated by the other side
    the TX link activates too, and when the other side deactivates its TX
    link this one deactivates once its queues are empty. A link this side
    did not initiate is held for the remote: it neither idles out nor
    drops for lack of a ``want(True)``; only ``want(False)`` (explicit) or
    the remote's own deactivation brings it down.

    B14.6.3.4 output ordering is obeyed against the local RX link's state
    (``remote_rx_state``, computed from the sampled RXLINKACTIVEREQ and the
    RXLINKACTIVEACK driven last cycle): REQ does not rise before the local
    ACK has fallen and does not fall before it has risen. B14.5: REQ never
    rises while the remote ACK is high and never falls while it is low.

    ``violations['ack_drop_with_credits']`` counts a remote ACK falling
    while this side still held credits (B14.5 Table B14.3: the receiver
    must have every credit back first).
    """

    def __init__(self, auto: bool = True, idle_deactivate: Optional[int] = 16):
        self.auto = bool(auto)
        self.idle_deactivate = idle_deactivate
        self.req = 0
        self._ack = 0                 # sampled LINKACTIVEACK
        self._want: Optional[bool] = None   # None = nothing asked; True = hold up; False = bring down
        self._initiated = False       # this side raised REQ for its own reasons (not following)
        self._idle = 0
        self._remote_rx = STOP
        self.violations: Dict[str, int] = {}
        self.stats = {'activations': 0, 'deactivations': 0}

    def reset(self) -> None:
        """B14.1.3: TXLINKACTIVEREQ deasserted in reset."""
        self.req = 0
        self._ack = 0
        self._initiated = False
        self._idle = 0
        self._remote_rx = STOP

    @property
    def state(self) -> str:
        return link_state(self.req, self._ack)

    def want(self, active: bool) -> None:
        """Manual activate (True) / deactivate (False). ``want(False)`` is
        explicit: it brings down a link the remote initiated as well, and
        once REQ has dropped the controller is back to asking nothing."""
        self._want = True if active else (False if self.req else None)

    def step(self, ack, have_work: bool, all_credits_returned: bool, remote_rx_state: str) -> int:
        """Returns LINKACTIVEREQ for this cycle. ``ack`` is the value
        sampled at the end of the previous cycle."""
        ack = int(ack)
        if self._ack and not ack and not all_credits_returned:
            _count(self.violations, 'ack_drop_with_credits')
        self._ack = ack
        st = link_state(self.req, ack)
        if st == STOP:
            own = self._want is True or (self.auto and bool(have_work))
            if self._may_raise(own, remote_rx_state):
                self.req = 1
                self._initiated = own
                self._idle = 0
                self.stats['activations'] += 1
        elif st == RUN:
            self._idle = 0 if have_work else self._idle + 1
            if self._may_drop(have_work, remote_rx_state):
                self.req = 0
                self.stats['deactivations'] += 1
                if self._want is False:
                    self._want = None
        self._remote_rx = remote_rx_state
        return self.req

    def _may_raise(self, own: bool, rx: str) -> bool:
        # B14.6.3.4: TXREQ must not rise before RXACK has fallen. A standing
        # RUN or a DEACTIVATE on the RX link means a deactivation is in
        # flight and this side waits for its own ACK to fall. RUN on the
        # cycle the RX link entered it is the ACK-with-REQ race (a wrapper
        # that stepped its RxLink first) and counts as "same cycle".
        if rx == DEACTIVATE or (rx == RUN and self._remote_rx in (RUN, DEACTIVATE)):
            return False
        follow = rx in (ACTIVATE, RUN)            # B14.6: the remote activated, so must we
        return follow or own

    def _may_drop(self, have_work: bool, rx: str) -> bool:
        if have_work or rx not in (RUN, DEACTIVATE):   # B14.6.3.4: not before RXACK has risen
            return False
        if rx == DEACTIVATE:                            # B14.6: follow the remote's deactivation
            return True
        if self._want is not None:
            return not self._want                       # explicit, either mode
        if not self._initiated:
            return False                                # held for the remote that raised it
        return (self.auto and self.idle_deactivate is not None
                and self._idle >= self.idle_deactivate)


class RxLink:
    """LINKACTIVEACK controller for the RX direction (all RX channels).

    ACK rises ``ack_delay()`` cycles after REQ is seen high (``enable``
    False never acknowledges) and falls only when REQ is low AND every
    credit of every RX channel has come back (B14.5 Table B14.3). The
    optional ``tx_req`` (this cycle's TXLINKACTIVEREQ) adds the B14.6.3.4
    output ordering: ACK neither rises before TXREQ has risen nor falls
    before it has fallen (same cycle allowed). Without it the two pairs
    are independent, which is the plain B14.5 behaviour.
    """

    def __init__(self, ack_delay: Optional[Callable[[], int]] = None, enable: bool = True):
        self.ack_delay = ack_delay
        self.enable = bool(enable)
        self.ack = 0
        self._req = 0                 # sampled LINKACTIVEREQ
        self._wait: Optional[int] = None
        self.stats = {'activations': 0, 'deactivations': 0}

    def reset(self) -> None:
        """B14.1.3: RXLINKACTIVEACK deasserted in reset."""
        self.ack = 0
        self._req = 0
        self._wait = None

    @property
    def state(self) -> str:
        return link_state(self._req, self.ack)

    def step(self, req, all_returned: bool, tx_req: Optional[int] = None) -> int:
        """Returns LINKACTIVEACK for this cycle. ``req`` is the value
        sampled at the end of the previous cycle."""
        req = int(req)
        self._req = req
        if req and not self.ack:
            if self.enable and (tx_req is None or int(tx_req)):
                if self._wait is None:
                    self._wait = _gap(self.ack_delay)
                if self._wait <= 0:
                    self.ack = 1
                    self._wait = None
                    self.stats['activations'] += 1
                else:
                    self._wait -= 1
        elif not req and self.ack:
            self._wait = None
            if all_returned and (tx_req is None or not int(tx_req)):
                self.ack = 0
                self.stats['deactivations'] += 1
        elif not req:
            self._wait = None
        return self.ack


class SActive:
    """TXSACTIVE bookkeeping (B14.7): asserted before or in the same cycle
    as the first flit of a transaction and held until after the last flit
    of all open transactions. Count transactions with :meth:`begin` /
    :meth:`end` before stepping the channels; :meth:`step` returns the
    value to drive. A node asserting TXSACTIVE must itself initiate link
    activation if needed, so feed the value into ``TxLink.step`` as work.
    """

    def __init__(self):
        self.open = 0
        self._prev_open = 0
        self.value = 0

    def reset(self) -> None:
        self.open = 0
        self._prev_open = 0
        self.value = 0

    def begin(self) -> None:
        self.open += 1

    def end(self) -> None:
        if self.open <= 0:
            raise RuntimeError("SActive.end() with no open transaction")
        self.open -= 1

    def step(self) -> int:
        self.value = int(self.open > 0 or self._prev_open > 0)
        self._prev_open = self.open
        return self.value


# ===========================================================================
# Passive checker (monitor side)
# ===========================================================================
class LinkChecker:
    """Passive per-port checker for a monitor: feed what the wires show each
    cycle (sampled at the falling edge) and read ``violations``.

    Channel keys are direction-qualified, ``'tx<ch>'`` / ``'rx<ch>'``
    (``'txreq'``, ``'rxdat'``), because an RN-F both sends and receives on
    RSP and DAT; a bare name is accepted when it is unambiguous. A channel
    missing from ``flits`` or ``lcrdv`` is idle that cycle.

    Kinds counted (each logged to ``messages``, bounded):

    * ``valid_without_pend``: FLITV without FLITPEND the cycle before (B14.4)
    * ``valid_without_credit``: FLITV with no usable credit; a credit is
      usable the cycle after LCRDV (B14.2.1.1)
    * ``credit_overflow``: more than ``max_credit`` credits at a transmitter
    * ``valid_not_run``: a flit outside RUN / DEACTIVATE (B14.5 Table B14.2)
    * ``credit_not_permitted``: LCRDV outside RUN (Table B14.3), except in
      the first ``deactivate_credit_grace`` cycles of DEACTIVATE ("may send
      some when first entering") and the credit-with-ACK race, which from
      the wires is simply RUN
    * ``handshake``: a four-phase step out of order (B14.5), or a
      B14.6.3.4 output ordering break between this port's TXLINKACTIVEREQ
      and RXLINKACTIVEACK (ACK rose before REQ rose / fell before REQ fell,
      REQ rose before ACK had fallen / fell before ACK had risen)
    * ``ack_drop_with_credits``: an ACK fell while that direction's
      transmitter held credits (Table B14.3)
    * ``lcrd_return_outside_deactivate``: an LCrdReturn flit (B13.11) on a
      link not in DEACTIVATE

    ``credits[key]`` is the modelled transmitter credit count per channel
    and ``max_credits[key]`` its peak: how a test proves a pool was used.
    """

    MAX_MESSAGES = 1000

    def __init__(self, max_credit: int = MAX_LCREDIT, tx_channels=(), rx_channels=(),
                 deactivate_credit_grace: int = 1, on_violation: Optional[Callable[[str, str], None]] = None):
        self.max_credit = int(max_credit)
        self.deactivate_credit_grace = int(deactivate_credit_grace)
        self.on_violation = on_violation
        self.channels: Dict[str, str] = {}
        for ch in tx_channels:
            self.channels[f"tx{ch}"] = 'tx'
        for ch in rx_channels:
            self.channels[f"rx{ch}"] = 'rx'
        self.credits: Dict[str, int] = {k: 0 for k in self.channels}
        self.max_credits: Dict[str, int] = {k: 0 for k in self.channels}
        self.violations: Dict[str, int] = {}
        self.messages = []
        self.stats = {'flits': 0, 'lcrd_returns': 0, 'grants': 0, 'activations': 0,
                      'deactivations': 0, 'cycles_run_tx': 0, 'cycles_run_rx': 0}
        self._link: Dict[str, Optional[tuple]] = {'tx': None, 'rx': None}   # previous (req, ack)
        self._deact_age: Dict[str, Optional[int]] = {'tx': None, 'rx': None}

    def reset(self) -> None:
        """Reset seen on the wires: no history, no credits (B14.1.3)."""
        for k in self.channels:
            self.credits[k] = 0
        self._link = {'tx': None, 'rx': None}
        self._deact_age = {'tx': None, 'rx': None}

    def total_violations(self) -> int:
        return sum(self.violations.values())

    def _violation(self, kind: str, msg: str) -> None:
        _count(self.violations, kind)
        if len(self.messages) < self.MAX_MESSAGES:
            self.messages.append(f"{kind}: {msg}")
        if self.on_violation is not None:
            self.on_violation(kind, msg)

    def _key(self, name: str) -> str:
        if name in self.channels:
            return name
        cands = [k for k in self.channels if k[2:] == name]
        if len(cands) == 1:
            return cands[0]
        raise KeyError(f"channel {name!r} is not one of {list(self.channels)} (use 'tx<ch>' / 'rx<ch>')")

    def check(self, txreq, txack, rxreq, rxack, flits: dict, lcrdv: dict) -> None:
        """One cycle of wire values. ``flits[key] = (flitpend, flitv,
        is_lcrd_return)`` where ``flitpend`` is the FLITPEND of the PREVIOUS
        cycle, the one that permits this cycle's FLITV (the monitor delays
        it; this checker does not delay it again). ``lcrdv[key]`` is this
        cycle's LCRDV."""
        links = {'tx': (int(txreq), int(txack)), 'rx': (int(rxreq), int(rxack))}
        held = {'tx': 0, 'rx': 0}
        for k, d in self.channels.items():
            held[d] += self.credits[k]
        for d, (req, ack) in links.items():
            self._check_link(d, req, ack, held[d])
        self._check_output_ordering(links)
        for name, d in self.channels.items():
            self._check_channel(name, d, links[d], flits, lcrdv)
        for d, (req, ack) in links.items():
            self._link[d] = (req, ack)
            if req and ack:
                self.stats[f"cycles_run_{d}"] += 1

    # -- link ----------------------------------------------------------------
    def _check_link(self, d: str, req: int, ack: int, held: int) -> None:
        prev = self._link[d]
        name = {'tx': 'TXLINK', 'rx': 'RXLINK'}[d]
        if prev is not None:
            pr, pa = prev
            if req != pr:
                if req and pa:
                    self._violation('handshake', f"{name}ACTIVEREQ rose while ACK still high (B14.5)")
                if not req and not pa:
                    self._violation('handshake', f"{name}ACTIVEREQ fell in ACTIVATE, before ACK (B14.5)")
                self.stats['activations' if req else 'deactivations'] += 1
            if ack != pa:
                if ack and not pr:
                    self._violation('handshake', f"{name}ACTIVEACK rose without REQ (B14.5)")
                if not ack and pr:
                    self._violation('handshake', f"{name}ACTIVEACK fell while REQ high (B14.5)")
                if not ack and held:
                    self._violation('ack_drop_with_credits',
                                    f"{name}ACTIVEACK fell with {held} credits at the transmitter (Table B14.3)")
        if (req, ack) == (0, 1):
            self._deact_age[d] = 0 if prev != (0, 1) else self._deact_age[d] + 1
        else:
            self._deact_age[d] = None

    def _check_output_ordering(self, links: dict) -> None:
        """B14.6.3.4 on this port's two outputs, TXLINKACTIVEREQ and
        RXLINKACTIVEACK. "Not before" allows the same cycle; "has fallen" /
        "has risen" means an earlier cycle."""
        ptx, prx = self._link['tx'], self._link['rx']
        if ptx is None or prx is None:
            return
        txreq, rxack = links['tx'][0], links['rx'][1]
        ptxreq, prxack = ptx[0], prx[1]
        if rxack and not prxack and not txreq:
            self._violation('handshake', "RXLINKACTIVEACK rose before TXLINKACTIVEREQ rose (B14.6.3.4)")
        if not rxack and prxack and txreq:
            self._violation('handshake', "RXLINKACTIVEACK fell before TXLINKACTIVEREQ fell (B14.6.3.4)")
        if txreq and not ptxreq and prxack:
            self._violation('handshake', "TXLINKACTIVEREQ rose before RXLINKACTIVEACK had fallen (B14.6.3.4)")
        if not txreq and ptxreq and not prxack:
            self._violation('handshake', "TXLINKACTIVEREQ fell before RXLINKACTIVEACK had risen (B14.6.3.4)")

    # -- channel ---------------------------------------------------------------
    def _lookup(self, table: dict, name: str, default):
        if name in table:
            return table[name]
        bare = name[2:]
        if bare in table and self._key(bare) == name:
            return table[bare]
        return default

    def _check_channel(self, name: str, d: str, link: tuple, flits: dict, lcrdv: dict) -> None:
        pend, v, ret = self._lookup(flits, name, (0, 0, False))
        g = int(self._lookup(lcrdv, name, 0))
        pend, v, ret = int(pend), int(v), bool(ret)
        st = link_state(*link)
        label = name.upper()
        if v:
            if not pend:
                self._violation('valid_without_pend', f"{label}FLITV without FLITPEND the cycle before (B14.4)")
            if self.credits[name] == 0:
                self._violation('valid_without_credit', f"{label}FLITV with no usable credit (B14.2.1.1)")
            if st not in (RUN, DEACTIVATE):
                self._violation('valid_not_run', f"{label}FLITV in {st} (B14.5 Table B14.2)")
            if ret and st != DEACTIVATE:
                self._violation('lcrd_return_outside_deactivate', f"{label} LCrdReturn in {st} (B13.11)")
            self.stats['lcrd_returns' if ret else 'flits'] += 1
        if g:
            age = self._deact_age[d]
            grace = st == DEACTIVATE and age is not None and age < self.deactivate_credit_grace
            if st != RUN and not grace:
                self._violation('credit_not_permitted', f"{label}LCRDV in {st} (B14.5 Table B14.3)")
            self.stats['grants'] += 1
        self.credits[name] = max(0, self.credits[name] - v) + g
        if self.credits[name] > self.max_credit:
            self._violation('credit_overflow',
                            f"{label}: {self.credits[name]} credits granted > max {self.max_credit} (B14.2.1.1)")
        self.max_credits[name] = max(self.max_credits[name], self.credits[name])


__all__ = ['STOP', 'ACTIVATE', 'RUN', 'DEACTIVATE', 'MAX_LCREDIT', 'LCRD_RETURN', 'link_state',
           'LCreditTx', 'LCreditRx', 'TxChannel', 'RxChannel', 'TxLink', 'RxLink', 'SActive',
           'LinkChecker']
