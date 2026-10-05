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

# IRQPacket

One observed transition on an interrupt line. This is the unit the
[IRQMonitor](irq_monitor.md) produces and the
[IRQMonitorGroup](irq_monitor_group.md) aggregates.

## Fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `time_ns` | float | 0.0 | Simulation time of the sampling edge, in ns |
| `count` | int | 0 | Monotonic index within the monitor that produced it |
| `name` | str | "" | The interrupt line's signal name, e.g. `'pit_timer_irq'` |
| `index` | int \| None | None | Bit index for a vector line; `None` for a scalar line |
| `event` | str | "assert" | `'assert'` or `'deassert'` |
| `value` | int | 0 | The WHOLE signal's value at the sampling edge |

## One Packet Per Changed Bit

The decomposition rule is the heart of the class: a transition produces one
packet per CHANGED BIT, not per sample. A vector line that asserts two bits in
the same cycle produces two packets — so a test can count events per line
without unpacking bit masks itself, and `events(index=N)` isolates one bit's
history.

The awkward case the decomposition gets right: one bit falling while another
rises in the SAME transition (`0b01 -> 0b10`). An OR-fabric monitor that
tracks only "something changed" reports this as a no-op or a single event;
`diff_to_packets` emits a `deassert` for bit 0 and an `assert` for bit 1. The
pure-function form is unit-tested exactly there
(`test_simultaneous_fall_and_rise_in_one_transition`).

## The value Field Carries Coincidence

`value` is the whole vector at the sampling edge, duplicated into every packet
the transition produces. That is not waste: the interesting bugs in an OR
fabric are about coincidence — "which other bits were also high when this one
asserted" is not recoverable from a per-bit event stream alone.

## Derived Labels

```python
pkt.line   # 'gpio_irq'        for a scalar
           # 'pit_timer_irq[1]' for a vector bit
str(pkt)   # 'pit_timer_irq[1] assert @ 1240.0ns (vec=0x2)'
```

`line` is what tests print and what `IRQMonitorGroup.all_events()` sorts by.

## Where Packets Come From

Tests normally never construct these — monitors do. The two places packets
are produced are `IRQMonitor._monitor_recv()` (its own coroutine) and
`IRQMonitor.sample()` (group-driven); both decompose through the pure function
`diff_to_packets(prev, cur, name, width, scalar, time_ns, start_count)`, which
is importable and testable without a simulator.

X/Z values never produce packets: an unresolvable read is treated as "no
event", not as a 0 (which would fabricate a deassert at reset time).
