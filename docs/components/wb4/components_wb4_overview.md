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

# Wishbone B4 Components Overview

## Scope

Wishbone B4, **pipelined** mode. The request side is `STB` under a `CYC`
envelope with `WE`, `ADR`, `DAT_W` (the spec's `DAT_O` at the master), `SEL`,
and an inverted ready called `STALL`. The termination side is exactly one of
`ACK`, `ERR`, `RTY` per clock with `DAT_R` (`DAT_I` at the master), pairing
with the OLDEST accepted request. There is no Wishbone B5; B4 is the current
revision and the one that added the pipelined mode.

Not modelled: `CTI`/`BTE` burst hints, `LOCK`, the `TG*` tag signals. Classic
(one-outstanding) peers interoperate by construction.

## Why these are not GAXI compositions

The AXI4 and AXI4-Lite families are built from GAXI channel components because
every AXI channel is a plain valid/ready pair. Wishbone is not:

- `STALL` is active-high "not ready" and may assert with no request pending.
- `CYC` spans the whole cycle, not one beat: a master holds it while requests
  are outstanding, and a slave treats a `CYC` drop as an abort.
- The termination has no ready, and its "valid" is three encoded signals that
  must pair with the oldest outstanding request.

So the family follows the APB shape (its own driver, responder and monitor on
`cocotb_bus`) while sharing every framework part: `FlexRandomizer` timing,
`MemoryModel`, `Packet` and `FieldConfig`.

## Timing convention

Outputs change right after the rising edge. Inputs are sampled at the falling
edge plus 200 ps, i.e. the value the next rising edge will see. A request is
accepted on the rising edge where `CYC && STB && !STALL`; a termination is
taken on the rising edge where one of `ACK/ERR/RTY` is high. The slave's
earliest termination is the edge after accept (latency 1, registered).

## Port naming

`prefix` is the port stem: `m_wb` binds `m_wb_CYC`, `m_wb_STB`, ... case-
insensitively. Write data may be `DAT_W`, `DAT_O`, `WDATA` or `DATA_W`; read
data `DAT_R`, `DAT_I`, `RDATA` or `DATA_R`; both resolve at bind time. `ERR`
and `RTY` are optional.

## Status encoding

`status` is 0 ACK, 1 ERR, 2 RTY, mirroring the RTL package `wb4_pkg` in the
main repository. If a broken slave asserts several, ERR wins, then RTY.

## Typical use

```python
from CocoTBFramework.components.wb4.wb4_factories import (
    create_wb4_master, create_wb4_slave, create_wb4_monitor)

# Testing a Wishbone master DUT: a slave BFM answers it, a monitor watches.
slave = create_wb4_slave(dut, "WB Slave", "m_wb", dut.clk, data_width=32,
                         status_hook=lambda p: 1 if p.adr >= 0xE000 else None)
mon   = create_wb4_monitor(dut, "WB Mon", "m_wb", dut.clk)
...
assert mon.total_violations() == 0 and mon.max_inflight > 1

# Testing a Wishbone slave DUT: a master BFM drives it.
master = create_wb4_master(dut, "WB Master", "s_wb", dut.clk, max_outstanding=8)
pkt = master.create_packet(we=1, adr=0x40, dat_w=0xCAFE, sel=0xF)
await master.busy_send(pkt)          # returns when this request terminated
assert pkt.status_name == "ACK"
master.abort()                       # drop CYC with requests outstanding
```

The monitor counts protocol violations rather than raising: `STB` without
`CYC`, a stalled request changed or withdrawn, more than one termination in a
clock, a termination outside a cycle or with nothing outstanding. It also
records `max_inflight`, which a test asserts is above one to prove the
pipelined mode was actually exercised.
