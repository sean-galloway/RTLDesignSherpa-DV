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

# IRQMonitor

Passive monitor for one interrupt line, scalar or vector. Samples on a clock
edge and emits one [IRQPacket](irq_packet.md) per CHANGED BIT. Level and pulse
lines are both handled: what is recorded is the transition, so a level that
stays high produces exactly one `assert`.

## Constructor

```python
IRQMonitor(entity, title, signal_name, clock,
           width=None, log=None, callback=None)
```

| Argument | Type | Meaning |
| --- | --- | --- |
| `entity` | SimHandle | DUT handle the signal lives on |
| `title` | str | Label used in log messages, e.g. `"RLB.gpio_irq"` |
| `signal_name` | str | Attribute name on the DUT, e.g. `'pit_timer_irq'` |
| `clock` | SimHandle | Clock to sample on (rising edge) |
| `width` | int, optional | Bit width; auto-detected from the signal when omitted |
| `log` | Logger, optional | Logger; defaults to `cocotb.irq.<title>` |
| `callback` | callable, optional | Called with each `IRQPacket` as it is captured |

Width auto-detection uses `len(signal)`; a signal with no length is treated
as width 1. A 1-bit result is reported as a SCALAR: packets carry `index=None`
and the line label is the bare signal name, so a test reads `gpio_irq`, not
`gpio_irq[0]`.

## Lifecycle

| Method | Meaning |
| --- | --- |
| `start()` | Arm the monitor: snapshot the current level and spawn the sampling coroutine. Idempotent. |
| `stop()` | Kill the sampling coroutine. |
| `clear()` | Drop captured packets and reset the assert/deassert counts. The sampled level itself is kept, so no spurious transition is recorded at the next sample. |

`start()` snapshots `_prev` from the line's CURRENT value, so driving that
happens after `start()` is a transition and driving that happened before it is
not.

## Observation

| Method / Property | Meaning |
| --- | --- |
| `recv_queue` | The captured packets, oldest first (a `deque`). |
| `assert_count` | Number of `assert` packets since construction/`clear()`. |
| `deassert_count` | Number of `deassert` packets since construction/`clear()`. |
| `is_asserted(index=None)` | Current level. `False` while the line is X/Z; for a vector, pass `index` to test one bit. |
| `events(event=None, index=None)` | Captured packets, optionally filtered by `'assert'`/`'deassert'` and/or bit index. |
| `get_stats()` | Dict: title, signal, width, asserts, deasserts, captured. |
| `sample(time_ns)` | Sample once, outside the coroutine — see below. |

### sample(): group-driven sampling

`sample()` is the trigger-free half of the monitor, split out so an
[IRQMonitorGroup](irq_monitor_group.md) can drive many monitors from ONE
coroutine. It reads the signal, decomposes any transition with
`diff_to_packets`, and records the packets. Calling it directly (with an
explicit timestamp) is also the easiest way to unit-test monitor behaviour
under a fake clock.

## Waiting

```python
await mon.wait_for_assert(index=None, timeout_ns=10000) -> bool
```

Awaits an assertion on the line and returns True if one is seen within
`timeout_ns`. The check is LEVEL-FIRST: if the line is already asserted when
the call is made, it returns immediately. That matters — a test that waits
for an edge it already missed would otherwise hang for the full timeout while
the evidence sits right there.

## Truthiness Contract

`IRQMonitor` is NEVER falsy, even when idle: it does not define `__len__` and
does not inherit cocotb's `Monitor` (whose queue-depth `__len__` makes an idle
monitor silently falsy). Write `if mon is not None:` when that is what you
mean; `if mon:` means `True`, always. A unit test pins this.

## Logging

Captured packets are logged at DEBUG as `<title>: <packet>`, where the packet
string is e.g. `pit_timer_irq[1] assert @ 1240.0ns (vec=0x2)`.
