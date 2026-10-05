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

# IRQMonitorGroup

Several interrupt lines watched as ONE unit. The point of the group is the
NEGATIVE assertion: a routing test wants to say "GPIO fired, so exactly these
lines moved and no others" — and the line that must NOT have moved (a cascade
input, a neighbouring IRQ) is where the real bugs are.

## Constructor

```python
IRQMonitorGroup(entity, clock, lines, title="IRQ", log=None)
```

| Argument | Type | Meaning |
| --- | --- | --- |
| `entity` | SimHandle | DUT handle |
| `clock` | SimHandle | Sampling clock (rising edge) |
| `lines` | dict[str, int \| None] | `{signal_name: width or None}`; `None` auto-detects |
| `title` | str | Label prefix; per-line monitors are titled `<title>.<name>` |
| `log` | Logger, optional | Logger; defaults to `cocotb.irq.<title>` |

A name in `lines` that does not exist on the DUT is skipped with a WARNING,
not an error — the same map can serve DUT variants that lack an optional
interrupt.

## Lifecycle

| Method | Meaning |
| --- | --- |
| `start()` | Snapshot every monitor's current level and spawn ONE shared sampling coroutine. Idempotent. |
| `stop()` | Kill the shared coroutine. |
| `clear()` | Clear every monitor (drops packets and counts, keeps sampled levels). |

### Why one coroutine

Each [IRQMonitor](irq_monitor.md) can sample itself, but a group started that
way runs one scheduler task per line — twelve wakeups per clock edge for a
twelve-line subsystem. Measured on the legacy `rlb_top` suite, that was the
difference between 187 s and 359 s. `IRQMonitorGroup.start()` instead runs a
single loop: one `RisingEdge` wait, then `sample(now)` on each monitor in
turn. Identical events for a fraction of the scheduler traffic. (The count
continuity guarantee survives: each monitor keeps its own `count` base, so
packet indices stay monotonic per line.)

## Set-Based Assertions

| Method | Meaning |
| --- | --- |
| `lines_asserted()` | Names of lines that saw at least one assert since the last `clear()`. |
| `currently_asserted()` | Names of lines whose level is high right now. |
| `all_events()` | Every captured packet across the group, sorted by `(time_ns, line)`. |
| `expect_only(expected)` | The headline assertion — see below. |
| `get_stats()` | Per-line stats dicts, keyed by line name. |

### expect_only: the negative assertion

```python
ok, missing, unexpected = irqs.expect_only(['gpio_irq', 'pic_int_out',
                                            'rlb_irq_out'])
```

Checks that EXACTLY the named lines have asserted since the last `clear()`.
Returns a tuple, not a bare bool:

- `ok` — `True` when the asserted set equals the expected set
- `missing` — sorted expected lines that never asserted (the IRQ you waited for never came)
- `unexpected` — sorted lines that asserted but were not expected (the spurious interrupt)

Naming the two difference sets is the whole diagnostic value: a failing
routing test can print "unexpected: ['pic_int_out']" instead of making you
diff the waveform by hand.

## Typical Pattern

```python
irqs = IRQMonitorGroup(dut, dut.pclk, {
    'gpio_irq': None, 'pic_int_out': None,
    'pit_timer_irq': None, 'rlb_irq_out': None,
}, title="RLB")
irqs.start()

irqs.clear()          # drop anything from setup
await trigger_stimulus()
await ClockCycles(dut.pclk, 20)

ok, missing, unexpected = irqs.expect_only(['gpio_irq', 'rlb_irq_out'])
assert ok, f"missing={missing} unexpected={unexpected}"
irqs.stop()
```

`clear()` before the stimulus (rather than relying on construction state) is
deliberate: it makes the assertion window explicit and immune to whatever
reset noise the setup phase produced.

## See Also

- [IRQMonitor](irq_monitor.md) — the per-line monitor this group drives
- [IRQ Components Overview](components_irq_overview.md) — the group sampling
  decision (187 s vs 359 s) and the falsy-monitor trap
