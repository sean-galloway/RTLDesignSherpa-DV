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

# wb4_components.py

`WB4Monitor`, `WB4Slave` and `WB4Master`: the Wishbone B4 pipelined BFMs on
the `cocotb_bus` chassis. See the [overview](components_wb4_overview.md) for
the timing convention and port naming.

## WB4Monitor(entity, title, prefix, clock, addr_width=32, data_width=32, classic=False, log=None)

Passive. Emits one `WB4Packet` per terminated transfer through the standard
`BusMonitor` callback/`_recvQ` path, request fields captured at accept and
termination fields at ACK/ERR/RTY, paired in order.

| Attribute | Meaning |
|---|---|
| `accepted`, `terminated` | running counts on the wires |
| `max_inflight` | peak accepted-not-terminated; proves pipelining happened |
| `aborts` | CYC dropped with requests outstanding (logged as a warning) |
| `violations` | `{kind: count}`; `total_violations()` sums it |
| `bursts` | `{cti: count}` over accepted transfers, classic ones excluded |

Violation kinds: `stb_without_cyc`, `request_changed`, `request_dropped`,
`multi_term`, `term_outside_cyc`, `term_without_request`.

The burst hints are part of the request the monitor holds the master to: a
master that changes `CTI` under a stalled `STB` is reported as
`request_changed`, exactly as if it had changed the address.

## WB4Slave(entity, title, prefix, clock, registers=None, addr_width=32, data_width=32, num_lines=1024, randomizer=None, max_outstanding=16, status_hook=None, classic=False, log=None)

A responder over a `MemoryModel` (`ADR` is a byte address; `SEL` is the
write strobe). Each accepted request is answered IN ORDER after a randomized
latency. Slave-via-BusMonitor, the framework convention.

Randomizer keys (bins are tuples, weights a list):

| Key | Meaning | Default |
|---|---|---|
| `stall` | clocks of STALL inserted after each accept | mostly 0, some 1..6 |
| `ack` | termination latency in clocks, >= 1 | mostly 1, some 2..4 |
| `status` | 0 ACK / 1 ERR / 2 RTY | 20:1:1 |

`status_hook(packet) -> int | None` overrides the status per request and is
where a test puts an ERR window, an RTY-once policy, and so on. `STALL` also
asserts while `max_outstanding` requests await termination. A master that
drops `CYC` with requests outstanding aborts them; `stats['aborted']` counts
them. Completed packets are in `sentQ`; `stats` has `accepted`, `ack`,
`err`, `rty`.

## WB4Master(entity, title, prefix, clock, addr_width=32, data_width=32, randomizer=None, max_outstanding=8, classic=False, log=None)

Queue `WB4Packet`s with `send()`; the pipeline presents one per clock while
the slave does not STALL, holds `CYC` until the last outstanding request has
terminated, and fills each packet's `status`/`dat_r` from the termination
that pairs with it, in order. `busy_send(pkt)` waits for that packet's
termination; `wait_idle()` for everything. Completed packets land in `sentQ`
and are delivered to `add_callback` callbacks.

| Key | Meaning | Default |
|---|---|---|
| `stb` | idle clocks before the next request is presented | mostly 0 |

`classic=True` holds each request until its termination, one at a time,
ignoring `STALL`. `max_outstanding` bounds requests in flight. `abort()` drops `CYC` on the
next edge and forgets the outstanding requests; the late terminations a
non-compliant slave still sends are counted in `stats['unexpected_term']`.
`create_packet(**fields)` builds a packet with this master's widths.

## Burst hints

`CTI` and `BTE` (B4 chapter 4) are optional on the port. When the bound DUT
has them the master drives each packet's `cti`/`bte`, and the slave and
monitor record what they sampled on the packet they build; when it does not,
every packet reads CLASSIC/LINEAR, which is what a tied-off bus carries
anyway. So a test never branches on which kind of bus it is on, and
`has_burst_hints` says which it got.

No BFM acts on a hint. They are advisory in B4, and deciding what a burst
means belongs to the peripheral -- so a hint changes nothing about how a
transfer terminates, and a test that wants burst behaviour has to model it
in a `status_hook`. `WB4Sequence.assign_burst_hints()` lays a plausible
pattern over a built sequence.
