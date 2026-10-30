"""CHI link layer (IHI 0050H chapter B14) without a simulator.

Figure B14.1 is reproduced cycle for cycle, the FLITPEND rule (B14.4) is
checked in both pend modes, the receiver's slot-backed grants (B14.2.1.1),
the link activation paths of Tables B14.4 / B14.5 as a closed loop of two
ports, LCrdReturn during DEACTIVATE (B13.11, Table B14.2), and the
LinkChecker against hand-built bad traces and the good traces above.
"""
from __future__ import annotations

import random

import pytest

from CocoTBFramework.components.chi.chi_link import (
    ACTIVATE,
    DEACTIVATE,
    LCRD_RETURN,
    RUN,
    STOP,
    LCreditRx,
    LCreditTx,
    LinkChecker,
    RxChannel,
    RxLink,
    SActive,
    TxChannel,
    TxLink,
    link_state,
)

S, A, R, D = STOP, ACTIVATE, RUN, DEACTIVATE


# ---------------------------------------------------------------------------
# Closed-loop harness: two ports wired back to back, rising-edge step then
# falling-edge sample, exactly the wrapper's timing convention.
# ---------------------------------------------------------------------------
class Port:
    def __init__(self, tx_chs, rx_chs, tx_max_credit=15, rx_max_credit=15, ack_delay=0, idle_deactivate=None,
                 auto=True, buffer_depth=None, pend_mode='exact', drain_gap=None, grant_gap=None, gate_ack=True):
        # a channel's credit limit belongs to its RECEIVER: tx_max_credit here equals the peer's rx_max_credit
        self.txlink = TxLink(auto=auto, idle_deactivate=idle_deactivate)
        self.rxlink = RxLink(ack_delay=lambda: ack_delay)
        self.gate_ack = gate_ack
        self.tx = {c: TxChannel(c, tx_max_credit, pend_mode) for c in tx_chs}
        self.rx = {c: RxChannel(c, rx_max_credit, buffer_depth, grant_gap=grant_gap, drain_gap=drain_gap)
                   for c in rx_chs}
        self.checker = LinkChecker(15, tx_chs, rx_chs)
        self.in_ack = self.in_req = 0
        self.in_lcrdv = {c: 0 for c in tx_chs}
        self.in_flit = {c: (0, False) for c in rx_chs}
        self.req = self.ack = 0
        self.out = {c: (0, 0, None) for c in tx_chs}
        self.lcrdv_out = {c: 0 for c in rx_chs}
        self.pend_prev = {c: 0 for c in tx_chs}
        self.sent = []          # (cycle, channel, flit)
        self.returns = []       # cycles an LCrdReturn went out
        self.ack_fell = []      # cycles our RXLINKACTIVEACK fell

    def have_work(self):
        return any(ch.queue for ch in self.tx.values())

    def step(self, cycle):
        remote_rx = link_state(self.in_req, self.ack)          # our RX link, last cycle's ACK
        tx_ret = all(ch.all_returned() for ch in self.tx.values())
        self.req = self.txlink.step(self.in_ack, self.have_work(), tx_ret, remote_rx)
        st = link_state(self.req, self.in_ack)
        for c, ch in self.tx.items():
            self.pend_prev[c] = self.out[c][0]
            self.out[c] = ch.step(st == RUN, st == DEACTIVATE, self.in_lcrdv[c])
            if self.out[c][1]:
                (self.returns if self.out[c][2] is LCRD_RETURN else self.sent).append(
                    cycle if self.out[c][2] is LCRD_RETURN else (cycle, c, self.out[c][2]))
        rx_ret = all(ch.credit.all_returned() for ch in self.rx.values())
        was = self.ack
        self.ack = self.rxlink.step(self.in_req, rx_ret, tx_req=self.req if self.gate_ack else None)
        if was and not self.ack:
            self.ack_fell.append(cycle)
        rst = link_state(self.in_req, self.ack)
        for c, ch in self.rx.items():
            v, ret = self.in_flit[c]
            self.lcrdv_out[c] = ch.step(rst == RUN, v, ret)

    def observe(self, remote):
        """What a monitor on this port sees this cycle."""
        flits = {f"tx{c}": (self.pend_prev[c], v, f is LCRD_RETURN) for c, (p, v, f) in self.out.items()}
        flits.update({f"rx{c}": (remote.pend_prev[c], v, f is LCRD_RETURN) for c, (p, v, f) in remote.out.items()})
        lcrdv = {f"tx{c}": remote.lcrdv_out[c] for c in self.tx}
        lcrdv.update({f"rx{c}": self.lcrdv_out[c] for c in self.rx})
        self.checker.check(self.req, remote.ack, remote.req, self.ack, flits, lcrdv)

    def sample(self, remote):
        self.in_ack, self.in_req = remote.ack, remote.req
        for c in self.tx:
            self.in_lcrdv[c] = remote.lcrdv_out[c]
        for c in self.rx:
            _, v, flit = remote.out[c]
            self.in_flit[c] = (v, flit is LCRD_RETURN)


def run_loop(a: Port, b: Port, cycles, hook=None):
    """Returns the wire-level (tx_state, rx_state) per cycle as seen from ``a``."""
    trace = []
    for n in range(cycles):
        if hook:
            hook(n)
        a.step(n)
        b.step(n)
        trace.append((link_state(a.req, b.ack), link_state(b.req, a.ack)))
        a.observe(b)
        b.observe(a)
        a.sample(b)
        b.sample(a)
    return trace


def dedupe(seq):
    out = []
    for s in seq:
        if not out or out[-1] != s:
            out.append(s)
    return out


def pair(a_kw=None, b_kw=None, a_holds=15, b_holds=15):
    """Two ports back to back. ``a_holds`` is the credit limit on the
    channels A transmits (B's receivers), ``b_holds`` the other way."""
    a = Port(('req', 'dat'), ('rsp',), tx_max_credit=a_holds, rx_max_credit=b_holds, **(a_kw or {}))
    b = Port(('rsp',), ('req', 'dat'), tx_max_credit=b_holds, rx_max_credit=a_holds, **(b_kw or {}))
    return a, b


def queue_work(port, n=3, at=1):
    """A hook that queues ``n`` flits on the port's first TX channel in
    cycle ``at`` (so cycle 0 shows the link at rest)."""
    ch = port.tx[next(iter(port.tx))]

    def hook(cycle):
        if cycle == at:
            ch.queue.extend(range(n))
    return hook


# ---------------------------------------------------------------------------
# (1) Figure B14.1
# ---------------------------------------------------------------------------
def test_figure_b14_1_exactly():
    """LCRDV in cycles 1,3,4,5,7; the figure's transmitter raises FLITPEND
    in 1,4,5,7 and so sends in 2,5,6,8; the credit counter reads
    0,0,1,0,1,2,2,1,2,1 across cycles 0..9."""
    lcrdv_cycles = {1, 3, 4, 5, 7}
    pend_cycles = {1, 4, 5, 7}
    ch = TxChannel('req')
    ch.queue.extend(range(100))
    flitv, counts, pends = [], [], []
    lcrdv_prev = 0                         # sampled at the end of the previous cycle
    for c in range(10):
        pend, v, flit = ch.step(True, False, lcrdv_prev, pend=int(c in pend_cycles))
        counts.append(ch.credit_count)
        pends.append(pend)
        if v:
            flitv.append(c)
            assert flit == len(flitv) - 1
        lcrdv_prev = int(c in lcrdv_cycles)
    assert flitv == [2, 5, 6, 8]
    assert counts == [0, 0, 1, 0, 1, 2, 2, 1, 2, 1]
    assert pends == [int(c in pend_cycles) for c in range(10)]
    assert ch.credit.credits == 1 and ch.stats['flits'] == 4
    assert ch.credit.stats['credits_received'] == 5 and ch.credit.stats['credits_spent'] == 4


def figure_trace():
    """Figure B14.1 as a monitor would see it on channel 'txreq', with a
    legal activation in front: a good trace for the LinkChecker."""
    lcrdv_cycles = {1, 3, 4, 5, 7}
    pend_cycles = {1, 4, 5, 7}
    ch = TxChannel('req')
    ch.queue.extend(range(100))
    rows = [((1, 0, 1, 0), (0, 0, False), 0), ((1, 1, 1, 1), (0, 0, False), 0)]
    lcrdv_prev, pend_prev = 0, 0
    for c in range(10):
        pend, v, _ = ch.step(True, False, lcrdv_prev, pend=int(c in pend_cycles))
        rows.append(((1, 1, 1, 1), (pend_prev, v, False), int(c in lcrdv_cycles)))
        lcrdv_prev, pend_prev = int(c in lcrdv_cycles), pend
    return rows


# ---------------------------------------------------------------------------
# (2) a credit is not usable the cycle it arrives
# ---------------------------------------------------------------------------
def test_credit_not_usable_same_cycle():
    pool = LCreditTx()
    pool.on_lcrdv(1)
    assert pool.pending == 1 and pool.credits == 0 and not pool.can_send()
    with pytest.raises(RuntimeError):
        pool.spend()
    pool.tick()
    assert pool.credits == 1 and pool.pending == 0 and pool.can_send()
    pool.spend()
    assert pool.credits == 0

    ch = TxChannel('rsp', pend_mode='always')
    ch.queue.append('x')
    ch.step(True, False, 0)                    # cycle n-1: FLITPEND up, nothing to pay with
    pend, v, _ = ch.step(True, False, 0)       # cycle n: LCRDV is high on the wire now
    assert v == 0 and ch.credit_count == 0
    pend, v, flit = ch.step(True, False, 1)    # cycle n+1: the credit sampled at the end of n
    assert v == 1 and flit == 'x' and ch.credit_count == 1


def test_credit_overflow_counted_not_clamped():
    pool = LCreditTx(max_credit=2)
    for _ in range(3):
        pool.on_lcrdv(1)
        pool.tick()
    assert pool.credits == 3 and pool.violations == {'credit_overflow': 1}


# ---------------------------------------------------------------------------
# (3) FLITV never without FLITPEND the cycle before
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ['exact', 'always'])
def test_flitv_only_after_flitpend(mode):
    rng = random.Random(3 if mode == 'exact' else 4)
    ch = TxChannel('dat', pend_mode=mode)
    pend_prev, sent, pend_zero, run = 0, 0, 0, True
    for c in range(2000):
        if rng.random() < 0.3:
            ch.queue.append(c)
        if rng.random() < 0.05:
            run = not run
        pend, v, _ = ch.step(run, False, int(rng.random() < 0.5))
        if v:
            assert pend_prev == 1, f"cycle {c}: FLITV without FLITPEND the cycle before"
            sent += 1
        pend_zero += int(pend == 0)
        pend_prev = pend
    assert sent > 100
    if mode == 'always':
        assert pend_zero == 0
    else:
        assert pend_zero > 0                     # 'exact' really does drop FLITPEND


def test_exact_pend_is_the_only_gate_once_credited():
    """With FLITPEND up and a credit usable, a queued flit goes at once."""
    ch = TxChannel('req', pend_mode='exact')
    assert ch.step(True, False, 0) == (0, 0, None)        # idle: no FLITPEND
    ch.queue.append('f')
    pend, v, _ = ch.step(True, False, 1)                  # credit usable, but no FLITPEND last cycle
    assert (pend, v) == (1, 0) and ch.stats['stall_cycles'] == 1
    assert ch.step(True, False, 0) == (0, 1, 'f')


# ---------------------------------------------------------------------------
# (4) the receiver never over-grants
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("max_credit, depth", [(15, 4), (3, None), (15, 15), (7, 20)])
def test_receiver_slot_backed_grants(max_credit, depth):
    rng = random.Random(max_credit * 31 + (depth or 0))
    tx = TxChannel('dat', max_credit, pend_mode='always')
    rx = RxChannel('dat', max_credit, depth, drain_gap=lambda: rng.choice([0, 0, 5, 40]))
    limit = depth if depth is not None else max_credit
    lcrdv_prev, flit_prev = 0, (0, False)
    peak = 0
    for c in range(3000):
        tx.queue.append(c)
        _, v, flit = tx.step(True, False, lcrdv_prev)
        lcrdv = rx.step(True, *flit_prev)
        cr = rx.credit
        assert cr.outstanding <= max_credit
        assert cr.buffered + cr.outstanding <= limit
        peak = max(peak, cr.outstanding)
        lcrdv_prev, flit_prev = lcrdv, (v, flit is LCRD_RETURN)
    assert peak >= 2 and rx.stats['grant_blocked'] > 0      # the bound actually bit
    assert rx.stats['flits'] > 100 and rx.credit.violations == {} and tx.violations == {}


def test_lcredit_rx_rules():
    rx = LCreditRx(max_credit=2, buffer_depth=3)
    rx.grant()
    rx.grant()
    assert not rx.grant_ok()                    # outstanding == max_credit
    with pytest.raises(RuntimeError):
        rx.grant()
    rx.on_flit(False)
    rx.on_flit(False)
    assert rx.outstanding == 0 and rx.buffered == 2 and rx.all_returned()
    rx.grant()
    assert not rx.grant_ok()                    # buffered + outstanding == buffer_depth
    rx.on_flit(True)                            # an LCrdReturn takes no slot
    assert rx.buffered == 2 and rx.outstanding == 0
    rx.on_flit(False)
    assert rx.violations == {'valid_without_credit': 1}
    rx.drain(3)
    assert rx.buffered == 0


# ---------------------------------------------------------------------------
# (5) STOP: credits accepted, nothing sent
# ---------------------------------------------------------------------------
def test_lone_transmitter_in_stop_never_sends():
    ch = TxChannel('req', pend_mode='always')
    ch.queue.extend('abc')
    for _ in range(20):
        _, v, _ = ch.step(False, False, 1)      # credits raced in, link not RUN
        assert v == 0
    assert ch.credit.held == 20 and ch.violations == {'credit_overflow': 5}
    assert ch.step(True, False, 0)[1] == 1     # RUN: the held credits are usable
    link = TxLink()
    for _ in range(50):
        assert link.step(0, have_work=False, all_credits_returned=True, remote_rx_state=S) == 0
    assert link.state == S and link.stats['activations'] == 0


# ---------------------------------------------------------------------------
# (6) Tables B14.4 / B14.5: activation and deactivation paths
# ---------------------------------------------------------------------------
ACT_PATHS = {
    'path1': [(S, S), (A, S), (A, A), (R, A), (R, R)],
    'path1_rx_first': [(S, S), (A, S), (A, A), (A, R), (R, R)],
    'path2': [(S, S), (S, A), (A, A), (A, R), (R, R)],
    'path2_tx_first': [(S, S), (S, A), (A, A), (R, A), (R, R)],
}
DEACT_PATHS = {
    'path1': [(R, R), (D, R), (D, D), (S, D), (S, S)],
    'path2': [(R, R), (D, R), (D, D), (D, S), (S, S)],
    'path3': [(R, R), (R, D), (D, D), (S, D), (S, S)],
    'path4': [(R, R), (R, D), (D, D), (D, S), (S, S)],
}
ORDER = {S: 0, A: 1, R: 2}


def legal_activation(path, initiator):
    """Each link steps STOP->ACTIVATE->RUN by at most one per cycle, both may
    step together, and the initiator's link leaves STOP first (or both)."""
    assert path[0] == (S, S) and path[-1] == (R, R)
    for (t0, r0), (t1, r1) in zip(path, path[1:]):
        assert 0 <= ORDER[t1] - ORDER[t0] <= 1 and 0 <= ORDER[r1] - ORDER[r0] <= 1
        assert (t1, r1) != (t0, r0)
    first = path[1]
    assert first[0] != S if initiator == 'tx' else first[1] != S


@pytest.mark.parametrize("initiator, d_a, d_b, name", [
    ('tx', 1, 1, 'path1'), ('tx', 0, 2, 'path1_rx_first'),
    ('rx', 1, 1, 'path2'), ('rx', 2, 0, 'path2_tx_first'),
])
def test_activation_paths(initiator, d_a, d_b, name):
    a, b = pair(dict(ack_delay=d_a), dict(ack_delay=d_b))
    trace = dedupe(run_loop(a, b, 12, hook=queue_work(a if initiator == 'tx' else b)))
    assert trace == ACT_PATHS[name], trace
    legal_activation(trace, initiator)
    assert a.checker.violations == {} and b.checker.violations == {}


def test_activation_path_sweep_is_always_legal():
    seen = set()
    for d_a in range(4):
        for d_b in range(4):
            for initiator in ('tx', 'rx'):
                a, b = pair(dict(ack_delay=d_a), dict(ack_delay=d_b))
                trace = dedupe(run_loop(a, b, 14, hook=queue_work(a if initiator == 'tx' else b, n=1)))
                legal_activation(trace, initiator)
                seen.add(tuple(trace))
                assert a.checker.violations == {} and b.checker.violations == {}
    assert all(tuple(v) in seen for v in ACT_PATHS.values())


def deactivation_run(initiator, a_holds, b_holds, cycles=80):
    """Bring the link up with traffic from ``initiator``, let it idle out
    (idle_deactivate on that side only), and return the ports and trace.
    The side with fewer credits to return lets the other's ACK fall first,
    which selects the path."""
    kw_init = dict(ack_delay=0, idle_deactivate=4)
    kw_other = dict(ack_delay=0, idle_deactivate=None)
    a, b = pair(kw_init if initiator == 'a' else kw_other, kw_other if initiator == 'a' else kw_init,
                a_holds=a_holds, b_holds=b_holds)
    trace = run_loop(a, b, cycles, hook=queue_work(a if initiator == 'a' else b, n=5))
    return a, b, trace


def deact_segment(trace):
    d = dedupe(trace)
    i = max(k for k, s in enumerate(d) if s == (R, R))
    return d[i:]


@pytest.mark.parametrize("initiator, a_holds, b_holds, name", [
    ('a', 2, 6, 'path1'),      # A initiates; A returns only 2 credits, so B's ACK falls first: (S, D)
    ('a', 6, 2, 'path2'),      # A initiates; B returns only 2, A's ACK falls first: (D, S)
    ('b', 2, 6, 'path3'),      # B initiates; B's ACK falls first
    ('b', 6, 2, 'path4'),      # B initiates; A's ACK falls first
])
def test_deactivation_paths(initiator, a_holds, b_holds, name):
    a, b, trace = deactivation_run(initiator, a_holds, b_holds)
    seg = deact_segment(trace)
    assert seg == DEACT_PATHS[name], seg
    assert trace[-1] == (S, S)
    assert a.checker.violations == {} and b.checker.violations == {}
    assert a.txlink.violations == {} and b.txlink.violations == {}


def test_full_cycle_activate_deactivate_reactivate():
    """Three rounds: A brings the link up and idles it down, then B does,
    then A again. The follower each time holds the link for the initiator
    and comes down with it."""
    a, b = pair(dict(ack_delay=1, idle_deactivate=3), dict(ack_delay=2, idle_deactivate=5))

    def hook(n):
        if n in (0, 60):
            a.tx['req'].queue.extend(range(4))
            a.tx['dat'].queue.extend(range(2))
        if n == 30:
            b.tx['rsp'].queue.extend(range(3))

    trace = run_loop(a, b, 120, hook)
    d = dedupe(trace)
    assert d.count((R, R)) == 3 and d[-1] == (S, S)
    assert a.txlink.stats == {'activations': 3, 'deactivations': 3}
    assert b.txlink.stats == {'activations': 3, 'deactivations': 3}
    assert len(a.sent) == 12 and len(b.sent) == 3
    assert b.rx['req'].stats['flits'] == 8 and b.rx['dat'].stats['flits'] == 4
    for p in (a, b):
        assert p.checker.violations == {}, p.checker.messages
        for ch in list(p.tx.values()) + list(p.rx.values()):
            assert ch.violations == {}
        assert all(ch.all_returned() for ch in p.tx.values())
        assert all(ch.credit.all_returned() for ch in p.rx.values())
    peak = a.tx['req'].credit.stats['max_credits']
    assert peak >= 4 and a.checker.max_credits['txreq'] == peak == b.checker.max_credits['rxreq']


# ---------------------------------------------------------------------------
# (7) DEACTIVATE returns every credit before ACK falls
# ---------------------------------------------------------------------------
def test_deactivate_returns_all_credits_then_ack_falls():
    a, b, trace = deactivation_run('a', 5, 6)
    # A held 5 credits on each of its two TX channels (B's receivers' limit), every one went back
    assert a.tx['req'].stats['lcrd_returns'] == 5 and a.tx['dat'].stats['lcrd_returns'] == 5
    assert a.tx['req'].credit.held == 0 and b.rx['req'].credit.outstanding == 0
    assert b.rx['req'].stats['lcrd_returns'] == 5
    assert len(b.ack_fell) == 1 and b.ack_fell[0] > max(a.returns)
    assert b.rxlink.stats['deactivations'] == 1
    # the deactivating side held credits on its RX side too: B returned A's 6
    assert b.tx['rsp'].stats['lcrd_returns'] == 6 and len(a.ack_fell) == 1 and a.ack_fell[0] > max(b.returns)


def test_credit_raced_into_deactivate_is_returned():
    """Table B14.2: in DEACTIVATE the transmitter keeps accepting credits
    and returns each one. The credit granted in the last RUN cycle arrives
    after REQ fell."""
    ch = TxChannel('rsp')
    ch.step(True, False, 0)
    _, v, _ = ch.step(False, True, 1)          # first DEACTIVATE cycle: the raced-in credit
    assert v == 0 and ch.credit_count == 1     # FLITPEND was low (idle), nothing yet
    pend, v, flit = ch.step(False, True, 1)    # a second one arrives; the first goes back
    assert (pend, v, flit) == (1, 1, LCRD_RETURN)
    pend, v, flit = ch.step(False, True, 0)
    assert (v, flit) == (1, LCRD_RETURN) and ch.all_returned()
    assert ch.stats == {'flits': 0, 'lcrd_returns': 2, 'stall_cycles': 0}
    assert ch.step(False, True, 0)[1] == 0


def test_rxlink_ack_falls_only_when_all_returned():
    rx = RxLink()
    assert rx.step(1, True) == 1 and rx.state == R
    assert rx.step(0, False) == 1 and rx.state == D   # credits still out
    assert rx.step(0, False) == 1
    assert rx.step(0, True) == 0 and rx.state == S
    rx = RxLink(ack_delay=lambda: 2)
    assert [rx.step(1, True) for _ in range(4)] == [0, 0, 1, 1]
    rx = RxLink(enable=False)
    assert [rx.step(1, True) for _ in range(4)] == [0, 0, 0, 0]
    rx = RxLink()                                      # B14.6.3.4 against our own TXREQ
    assert rx.step(1, True, tx_req=0) == 0
    assert rx.step(1, True, tx_req=1) == 1
    assert rx.step(0, True, tx_req=1) == 1
    assert rx.step(0, True, tx_req=0) == 0


def test_txlink_rules():
    tx = TxLink(auto=True, idle_deactivate=2)
    assert tx.step(0, True, True, S) == 1 and tx.state == A
    assert tx.step(0, True, True, A) == 1              # hold in ACTIVATE
    assert tx.step(1, True, True, A) == 1 and tx.state == R
    assert tx.step(1, False, True, A) == 1              # idle 1
    assert tx.step(1, False, True, A) == 1              # idle 2, but our RX ACK has not risen
    assert tx.step(1, False, True, R) == 0 and tx.state == D
    assert tx.step(1, True, True, R) == 0               # DEACTIVATE: hold until ACK falls
    assert tx.step(0, True, True, R) == 0 and tx.state == S   # (STOP, RUN): wait for our ACK to fall
    assert tx.step(0, True, True, D) == 0
    assert tx.step(0, True, True, S) == 1               # now it may rise again
    assert tx.stats == {'activations': 2, 'deactivations': 1}
    # the remote activating our RX link activates TX with no work and no want
    tx = TxLink(auto=False)
    assert tx.step(0, False, True, A) == 1
    assert tx.step(1, False, True, R) == 1              # a follower holds the link for the remote
    tx.want(False)
    assert tx.step(1, False, True, R) == 0              # explicit deactivate
    assert tx.step(0, True, True, S) == 0               # manual: work alone does not raise it
    tx.want(True)
    assert tx.step(0, False, True, S) == 1
    # an auto follower does not idle out either
    tx = TxLink(auto=True, idle_deactivate=1)
    tx.step(0, False, True, A)
    assert all(tx.step(1, False, True, R) == 1 for _ in range(10))
    # want(False) is one-shot: afterwards idleness rules again
    tx = TxLink(auto=True, idle_deactivate=3)
    tx.want(True)
    tx.step(0, False, True, S)
    tx.step(1, False, True, R)
    tx.want(False)
    assert tx.step(1, False, True, R) == 0
    tx.step(0, True, True, S)
    assert tx.step(0, True, True, S) == 1
    assert [tx.step(1, False, True, R) for _ in range(4)] == [1, 1, 0, 0]
    # the remote deactivating pulls REQ down even while wanted, once the queue is empty
    tx = TxLink(auto=True, idle_deactivate=None)
    tx.want(True)
    tx.step(0, False, True, S)
    assert tx.step(1, True, True, R) == 1
    assert tx.step(1, True, True, D) == 1               # work left: finish it first
    assert tx.step(1, False, True, D) == 0
    # ACK fell while credits were still held
    tx = TxLink()
    tx.step(0, True, True, S)
    tx.step(1, True, True, R)
    tx.step(0, True, False, R)
    assert tx.violations == {'ack_drop_with_credits': 1}


def test_sactive():
    s = SActive()
    assert s.step() == 0
    s.begin()
    assert s.step() == 1
    s.end()
    assert s.step() == 1                                # held one cycle after the last flit
    assert s.step() == 0
    with pytest.raises(RuntimeError):
        s.end()


def test_reset_deasserts_everything():
    a, b = pair(dict(ack_delay=0, idle_deactivate=None), dict(ack_delay=0))
    a.tx['req'].queue.extend(range(3))
    run_loop(a, b, 10)
    assert a.txlink.req == 1 and b.rxlink.ack == 1 and a.tx['req'].credit.held > 0
    for m in (a.txlink, b.rxlink, a.tx['req'], b.rx['req'], a.checker):
        m.reset()
    assert a.txlink.req == 0 and a.txlink.state == S and b.rxlink.ack == 0 and b.rxlink.state == S
    assert a.tx['req'].credit.held == 0 and a.tx['req'].flitpend == 0
    assert b.rx['req'].credit.outstanding == 0 and b.rx['req'].lcrdv == 0
    assert all(v == 0 for v in a.checker.credits.values())


# ---------------------------------------------------------------------------
# (8) LinkChecker
# ---------------------------------------------------------------------------
IDLE = {'txreq': (0, 0, False)}
NOCRD = {'txreq': 0}


def feed(chk, rows):
    for (txreq, txack, rxreq, rxack), flit, g in rows:
        chk.check(txreq, txack, rxreq, rxack, {'txreq': flit}, {'txreq': g})


def test_checker_silent_on_figure_trace():
    chk = LinkChecker(tx_channels=('req',), rx_channels=('rsp',))
    feed(chk, figure_trace())
    assert chk.violations == {}, chk.messages
    assert chk.stats['flits'] == 4 and chk.stats['grants'] == 5 and chk.max_credits['txreq'] == 2
    assert chk.credits['txreq'] == 1


def test_checker_silent_on_closed_loop_traces():
    for initiator, ah, bh in [('a', 2, 6), ('a', 6, 2), ('b', 2, 6), ('b', 6, 2)]:
        a, b, _ = deactivation_run(initiator, ah, bh)
        assert a.checker.violations == {} and b.checker.violations == {}
        assert a.checker.stats['activations'] == 2 and a.checker.stats['deactivations'] == 2   # both links


def test_checker_accepts_bare_channel_names_when_unique():
    chk = LinkChecker(tx_channels=('req', 'rsp'), rx_channels=('rsp',))
    chk.check(1, 1, 1, 1, {}, {'req': 1})
    assert chk.credits['txreq'] == 1
    with pytest.raises(KeyError):
        chk.check(1, 1, 1, 1, {}, {'rsp': 1})


def up(chk):
    """A legal activation on both links (TXREQ first, then RXACK)."""
    feed(chk, [((1, 0, 1, 0), (0, 0, False), 0), ((1, 1, 1, 1), (0, 0, False), 0)])
    assert chk.violations == {}


def test_checker_valid_without_pend():
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 1), ((1, 1, 1, 1), (0, 1, False), 0)])
    assert chk.violations == {'valid_without_pend': 1}


def test_checker_valid_without_credit():
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (1, 1, False), 0)])
    assert chk.violations == {'valid_without_credit': 1}
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (1, 1, False), 1)])        # the credit arriving this cycle does not count
    assert chk.violations == {'valid_without_credit': 1}


def test_checker_credit_overflow():
    chk = LinkChecker(max_credit=15, tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 1)] * 16)
    assert chk.violations == {'credit_overflow': 1} and chk.credits['txreq'] == 16


def test_checker_valid_not_run_and_credit_not_permitted():
    chk = LinkChecker(tx_channels=('req',))
    feed(chk, [((0, 0, 0, 0), (0, 0, False), 1)])          # LCRDV in STOP
    assert chk.violations == {'credit_not_permitted': 1}
    feed(chk, [((1, 0, 1, 0), (1, 0, False), 0), ((1, 0, 1, 0), (1, 1, False), 0)])   # FLITV in ACTIVATE
    assert chk.violations == {'credit_not_permitted': 1, 'valid_not_run': 1}
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 0), ((0, 1, 1, 1), (0, 0, False), 1)])   # entering DEACTIVATE: allowed
    assert chk.violations == {}
    feed(chk, [((0, 1, 1, 1), (0, 0, False), 1)])          # a cycle later it is not
    assert chk.violations == {'credit_not_permitted': 1}


def test_checker_handshake_four_phase_and_output_ordering():
    chk = LinkChecker(tx_channels=('req',))
    feed(chk, [((0, 0, 0, 0), (0, 0, False), 0), ((0, 1, 0, 0), (0, 0, False), 0)])   # ACK without REQ
    assert chk.violations == {'handshake': 1}
    chk = LinkChecker(tx_channels=('req',))
    feed(chk, [((0, 0, 0, 0), (0, 0, False), 0), ((0, 0, 1, 1), (0, 0, False), 0)])
    # RX ACK rose with REQ in the same cycle (four-phase) AND before our TXREQ rose (B14.6.3.4)
    assert chk.violations == {'handshake': 2}
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 0), ((1, 1, 0, 1), (0, 0, False), 0),
               ((1, 1, 0, 0), (0, 0, False), 0)])         # RXACK fell before TXREQ fell
    assert chk.violations == {'handshake': 1}
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((0, 1, 1, 1), (0, 0, False), 0)])          # TXREQ fell: fine, RXACK had risen
    assert chk.violations == {}
    feed(chk, [((0, 0, 1, 1), (0, 0, False), 0), ((1, 0, 1, 1), (0, 0, False), 0)])   # rose before RXACK fell
    assert chk.violations == {'handshake': 1}
    chk = LinkChecker(tx_channels=('req',))
    feed(chk, [((1, 0, 0, 0), (0, 0, False), 0), ((1, 1, 0, 0), (0, 0, False), 0),
               ((0, 1, 0, 0), (0, 0, False), 0)])         # TXREQ fell before RXACK had risen
    assert chk.violations == {'handshake': 1}


def test_checker_ack_drop_with_credits():
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 1), ((0, 1, 1, 1), (0, 0, False), 0),
               ((0, 0, 1, 1), (0, 0, False), 0)])
    assert chk.violations == {'ack_drop_with_credits': 1}


def test_checker_lcrd_return_outside_deactivate():
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 1), ((1, 1, 1, 1), (1, 1, True), 0)])
    assert chk.violations == {'lcrd_return_outside_deactivate': 1}
    chk = LinkChecker(tx_channels=('req',))
    up(chk)
    feed(chk, [((1, 1, 1, 1), (0, 0, False), 1), ((0, 1, 1, 1), (0, 0, False), 0),
               ((0, 1, 1, 1), (1, 1, True), 0)])          # in DEACTIVATE it is the right thing
    assert chk.violations == {}


def test_checker_reset_and_no_link_control():
    chk = LinkChecker(tx_channels=('req',), rx_channels=('rsp',))
    for _ in range(3):
        chk.check(1, 1, 1, 1, {}, {})                      # link_control=False wrappers feed 1,1,1,1
    assert chk.violations == {}
    up_rows = figure_trace()
    feed(chk, up_rows[2:4])
    chk.reset()
    assert chk.credits['txreq'] == 0
    chk.check(1, 1, 1, 1, {}, {})
    assert chk.violations == {}
    chk.check(1, 1, 1, 1, {'txreq': (1, 1, False)}, {})
    assert chk.violations == {'valid_without_credit': 1}
