<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

**[← Back to IRQ Components](index.md)** | **[Components Index](../components_index.md)**

# IRQ Components Overview

The IRQ family is the smallest component set in the framework, and that is
deliberate: an interrupt line is the simplest interface there is. One wire (or
one vector of wires), no handshake, no data payload — the event IS the level
change. Everything on this page is about getting the small things right,
because interrupt tests fail on exactly those: a pulse missed between polls, a
line that was expected to stay quiet and didn't, a vector where bit 0 fell in
the same cycle bit 1 rose.

## When to Use This Family

Use it when ALL of these hold:

- The signal is a plain level or pulse line — GPIO interrupt, PIC output,
  timer IRQ, cascade input.
- There is no `valid`/`ready` handshake on the delivery path.
- You care about WHEN lines moved and WHICH lines moved — including the ones
  that must NOT move.

Use GAXI instead the moment a handshake exists. The dividing case in this
repo's legacy subsystem is the IOAPIC delivery channel: `irq_out_valid` /
`irq_out_ready` / `irq_out_retry` is a GAXI interface wearing an interrupt
costume. Routing it here would record only "the line changed", losing the
retry behaviour that is where its bugs live.

## Why Not Just Poll in the Test

Before this family existed, the legacy-subsystem tests observed interrupts by
hand — `int(dut.sig.value)` inside a polling loop, in twelve different places,
each with its own timeout, sample rate, and definition of "an event". Three
failure modes come with that, and all three were observed:

1. **Missed pulses.** A polled loop samples every N cycles; a pulse narrower
   than the poll interval never existed as far as the test is concerned. A
   monitor sampling every clock edge does not have that hole.
2. **No timestamp.** "It asserted" and "it asserted 40 ns after the write that
   should cause it" are different assertions. Every packet carries the
   simulation time of the sampling edge.
3. **No two call sites agree.** One loop counts edges, another counts levels,
   a third just waits. Centralising the observation in one monitor class means
   the definition of "assert" lives in exactly one place.

## Design Decisions

### Standalone, Not on GAXI

Every other component family here (AXI, AXIS, FIFO, GAXI itself) is built on
the GAXI pipeline layer. IRQ is not, on purpose: there is no handshake to
pipeline. The monitor depends only on cocotb and the standard library, which
also makes it cheap to reuse in testbenches that do not otherwise use the
framework.

### The Falsy-Monitor Trap, Structurally Avoided

cocotb's `Monitor` defines `__len__` as the receive-queue depth, which makes
an IDLE monitor FALSY in Python. `mon.get_stats() if mon else {}` then
silently returns `{}` — and an idle interrupt line is the NORMAL case, so the
trap would fire constantly. `IRQMonitor` therefore does not inherit
`cocotb.Monitor` and does not define `__len__`: `if mon:` is always True, and
an explicit `is not None` check means what it says. There is a unit test
pinning this (`test_monitor_is_never_falsy_even_when_idle`), because a
regression here would be silent.

### One Coroutine per Group, Not per Line

Each `IRQMonitor` can run its own sampling coroutine, and for one or two
lines that is fine. For the twelve-line legacy top level it was not: twelve
tasks each awaiting `RisingEdge` every clock costs twelve scheduler wakeups
per edge, and when the group was first wired into `rlb_top` that way the suite
went from 187 s to 359 s. `IRQMonitorGroup` runs ONE coroutine that waits a
single edge and then calls `sample()` on every monitor in the group —
identical events for a twelfth of the scheduler traffic. The per-monitor
`start()` remains for the single-line case.

### Transitions, Not Levels

What is recorded is the TRANSITION between sampled values, so level and pulse
lines are handled uniformly: a level that goes high produces exactly one
`assert` packet and then silence, however long it stays high; a pulse produces
`assert` then `deassert`. The decomposition into packets is a pure function
(`diff_to_packets`), extracted so the logic — including the awkward case of
one bit falling while another rises in the SAME transition — is testable in
plain Python without standing up a simulation.

### X/Z Means "No Event", Not Zero

Interrupt lines are X before reset deasserts. Reading X as 0 would fabricate
deassert events at time zero, and raising would kill the sampling coroutine
silently (nothing awaits it). `_resolve` returns `None` for unresolvable
values and the sampler treats that as "carry the previous value forward".

### The Negative Assertion Is the Point

The bug you are looking for in an interrupt-routing test is almost never
"my line did not fire". It is "a line fired that should not have" — the
cascade input, the neighbouring bank, the spurious assert. `expect_only`
exists for that: it checks the set of lines that asserted since the last
`clear()` against an expected set and returns `(ok, missing, unexpected)` so
a failure names the offending line instead of returning a bare False.

## Package Layout

```
src/CocoTBFramework/components/irq/
├── __init__.py          # re-exports IRQMonitor, IRQMonitorGroup, IRQPacket
├── irq_packet.py        # IRQPacket — one observed transition
└── irq_components.py    # IRQMonitor, IRQMonitorGroup, diff_to_packets, _resolve
```

History: written in RTLDesignSherpa's `bin/TBClasses/irq` on 2026-09-28 to
iterate without a package reinstall, promoted into the framework as
cocotb-framework **1.0.0** (2026-10-04). The RDS-side copy was removed; its
consumers (`rlb_top` among them) import from here.

## See Also

- [GAXI Components](../gaxi/components_gaxi_index.md) — for lines WITH a
  handshake, which is the complement of this family
- Unit tests: `tests/unit/test_irq_logic.py` — the pure-Python decomposition
  cases, runnable without a simulator
