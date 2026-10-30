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

# CXS Components Overview

## Scope

CXS is Arm's Credited eXtensible Stream protocol (*AMBA CXS Protocol Specification*, ARM IHI 0079). It is a point-to-point packet stream for wide links, typically between an interconnect and a PCIe controller carrying CCIX or CXL. This family covers **all four published issues** and CXS-Lite:

| Issue | Adds |
|---|---|
| A (2018) | CXSDATAFLITWIDTH 256/512/1024, CXSMAXPKTPERFLIT 2..4, up to 15 credits, Odd_Byte_Parity, Explicit_Credit_Return link control |
| B (2020) | CXSLAST, CXSPRCLTYPE (multiple protocol streams) |
| C (2023) | One packet per flit (no CXSCNTL, width 8..2048), up to 63 credits |
| D (2025) | 2048-bit multi-packet flits, 4-byte start alignment, CXSSRCID/CXSTGTID, CXSUSER, CXS-Lite named |

Each issue is a strict superset of the previous one, so the family is a single code base. An issue is a set of legal property values: `CXSConfig(issue='B', ...)`, then `.validate()` says whether the properties are legal for that issue and names the broken rule if not. The rule numbering matches `cxs_pkg::config_error` in the RTLDesignSherpa RTL.

## Why These Are Not GAXI Compositions

CXS has no READY. A flit moves when the transmitter spends a credit. Credits arrive one per cycle on CXSCRDGNT and can go back on CXSCRDRTN. Link activation is a four-phase CXSACTIVEREQ/CXSACTIVEACK handshake that gates both. None of that is a valid/ready pair, so, like the Wishbone family, each BFM runs its own clocked loop while sharing the framework parts: `Packet` (as `CXSFlit`), `FieldConfig`, `FlexRandomizer` timing, and a `_recvQ` plus callbacks.

## Components

| Class | Role |
|---|---|
| `CXSConfig`, `CXSIssue` | Interface properties, per-issue legality, CXSCNTL layout, check widths, `rtl_parameters()` |
| `CXSCntl` | Encode/decode one CXSCNTL word; `violations()` lists every format and placement rule it breaks |
| `CXSPacket`, `CXSFlit` | A packet (bytes plus stream and ENDERROR) and one cycle on the wire |
| `CXSPacketizer` / `CXSDepacketizer` | Packets to flits by the 4.1 placement rules, and back, with checking |
| `CXSTransmitter` | Drives a receiver DUT: credits, link activation, CRDRTN, check-signal generation and error injection |
| `CXSReceiver` | Drives a transmitter DUT: a buffer-backed credit pool, ACK, DEACTHINT, packet reassembly |
| `CXSMonitor` | Passive: flits, packets, a credit model and the protocol checks |

## Timing Convention

Outputs change right after the rising edge, and inputs are sampled at the falling edge, the APB/WB4 convention. This matches the spec's credit timing exactly:

- A credit sampled in cycle t is spent in cycle t+1 at the earliest (2.1.2).
- A credit consumed or returned in cycle t is re-granted in t+1 at the earliest.
- ACTIVEACK sampled in cycle t lets the transmitter send in t+1.

## Port Naming

Binding goes through the shared `SignalResolver` (`components/shared/signal_mapping_helper.py`, protocol type `cxs`), like every family. `prefix` and `bus_name` are tried with and without a trailing underscore over the spellings a port may use, so each of these finds the same pin without a `signal_map`:

| DUT port | Binding |
|---|---|
| `m_cxs_crdgnt` | `prefix='m_cxs_'`, or `prefix='m_'` (the `cxs` / `cxs_` infix is tried) |
| `s_cxs_crd_gnt`, `s_cxs_prcl_type`, `s_cxs_active_req` | `prefix='s_cxs_'` (underscored spellings) |
| `CXSTXCRDGNT` | `prefix='CXSTX'` (the spec's upper-case names) |
| `u_link_cxs_valid` | `prefix='u_'`, `bus_name='link'` |

Only the signals the `CXSConfig` says the port has are required of the DUT; a missing one fails construction naming every spelling that was tried. `signal_map={'crdgnt': 'odd_pin'}` overrides any subset by logical name (the keys are the names in the table below) and discovery resolves the rest; an unknown key is rejected, which catches typos. The resolver is `bfm.resolver` if you need to see what it bound. `tests/unit/test_flat_signal_resolver.py` pins these spellings.

## Quick Start

```python
from CocoTBFramework.components.cxs import (
    CXSConfig, CXSPacket, create_cxs_transmitter, create_cxs_monitor)

cfg = CXSConfig(issue='B', data_width=512, max_pkt_per_flit=2,
                has_last=True, check=True)
tx  = create_cxs_transmitter(dut, "TX", "s_cxs_", dut.aclk, cfg, reset=dut.aresetn)
mon = create_cxs_monitor(dut, "Mon", "s_cxs_", dut.aclk, cfg, reset=dut.aresetn)

tx.send_packets([CXSPacket(bytes(range(40))), CXSPacket(bytes(12), end_error=True)])
await tx.wait_idle()
assert mon.packets == ...            # reassembled from the wires
assert mon.total_violations() == 0, mon.violations
```

## Monitor Checks

Each kind is counted in `violations` and logged, never raised:

| Kind | Rule |
|---|---|
| `valid_without_credit` | A flit with no usable credit (a credit is usable the cycle after its grant) |
| `valid_with_crdrtn` / `return_without_credit` | 2.1.2 |
| `credit_overflow` | More credits outstanding than CXS_MAX_CREDIT |
| `valid_not_run` | A flit outside RUN |
| `credit_not_permitted` | A grant in STOP or ACTIVATE |
| `handshake` | A four-phase step out of order |
| `ack_drop_with_credits` | ACTIVEACK fell while the transmitter held credits (5.6) |
| `deactivate_in_packet` | With CXSCONTINUOUSDATA, ACTIVEREQ fell inside a packet (6.1) |
| `cntl` | A CXSCNTL or placement rule (via `CXSDepacketizer`) |
| `parity_<signal>` | An Odd_Byte_Parity mismatch, with each check signal's own enable |

## Used By

RTLDesignSherpa `val/amba/test_cxs_{master,slave}[_cg].py` drive `rtl/amba/cxs/` with these BFMs across Issues A-D.
