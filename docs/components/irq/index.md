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

**[← Back to Components Index](../components_index.md)** | **[CocoTBFramework Index](../components_index.md)** | **[Main Index](../components_index.md)**

# IRQ Components

Passive observation for plain interrupt lines — level or pulse, scalar or vector. An interrupt wire has no handshake, so it gets its own monitor instead of riding the GAXI machinery: sample on a clock edge, decompose the transition into one packet per changed bit, and answer the questions interrupt tests actually ask ("did this line assert, when, and did anything ELSE move?").

## Component Overview

| Component | Purpose |
| --- | --- |
| [IRQMonitor](irq_monitor.md) | Passive monitor for ONE interrupt line, scalar or vector. Samples on a clock edge and emits one `IRQPacket` per changed bit. |
| [IRQMonitorGroup](irq_monitor_group.md) | Several lines watched as one unit, from ONE sampling coroutine, with set-based assertions (`expect_only`) for the negative case. |
| [IRQPacket](irq_packet.md) | One observed transition on one line — time, per-bit index, whole-vector value. |

## Pages

- [IRQ Components Overview](components_irq_overview.md) — when to use this family, when NOT to, and the design decisions behind it
- [IRQMonitor](irq_monitor.md) — per-line monitor API
- [IRQMonitorGroup](irq_monitor_group.md) — group API, single-coroutine sampling, `expect_only`
- [IRQPacket](irq_packet.md) — the transition packet

## Quick Start

```python
from CocoTBFramework.components.irq import IRQMonitorGroup

irqs = IRQMonitorGroup(dut, dut.pclk, {
    'gpio_irq':      None,     # width auto-detected
    'pic_int_out':   None,
    'pit_timer_irq': None,     # vector: one event per bit
    'rlb_irq_out':   None,
}, title="RLB")
irqs.start()
# ... run the stimulus ...
ok, missing, unexpected = irqs.expect_only(['gpio_irq', 'pic_int_out',
                                            'rlb_irq_out'])
irqs.stop()
```

A line named in the map that does not exist on the DUT is skipped with a
warning, so the same map can serve several DUT variants.

## The One Rule

**A line with a handshake is not an interrupt line.** The moment a delivery
channel grows `valid`/`ready`/`retry` — the IOAPIC's `irq_out_valid` /
`irq_out_ready` / `irq_out_retry`, for instance — it belongs to GAXI, not here.
This family is only for wires where assertion IS the event.
