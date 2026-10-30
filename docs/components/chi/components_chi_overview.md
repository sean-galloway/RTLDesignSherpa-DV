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

# CHI Components Overview

## Scope

CHI is Arm's Coherent Hub Interface (*AMBA CHI Architecture Specification*, Arm IHI 0050). This family is written to **Issue H** and nothing else: `CHIConfig(issue='G')` fails rule 1, because field widths changed between issues and a G layout is not an H layout. One frozen `CHIConfig` per port carries the B16.1 properties that change a flit's layout or a link's behaviour; which opcodes a node may use is a property of the BFM, not of the config.

What is modelled:

| Area | Spec | Modelled |
|---|---|---|
| Flit layouts | Tables B13.6 to B13.9 | All four channels, every optional bus as a width (RSVDC, MPAM, PBHA, MECID, StreamID, SecSID1, DataCheck, Poison), NodeID 7 to 16, RAW 44 to 52, DW 128 / 256 / 512 |
| Link layer | Chapter B14 | L-Credits per channel (1 to 15), FLITPEND, LCrdReturn, LINKACTIVEREQ/ACK per direction, the B14.6.3.4 output ordering, TXSACTIVE/RXSACTIVE |
| Transactions | B2.3, B2.4, B2.7.3, B2.9.4, B2.10 | Allocating and non-allocating reads, dataless, immediate and CopyBack writes, PCrdReturn; CompAck; DBID rendezvous; DataID chunking; RetryAck / PCrdGrant |
| Coherence | Chapter B4 | RN-F cache states and the Requester tables B4.38 / B4.41 / B4.42 / B4.43 / B4.44, the Snoopee tables B4.46 to B4.50, a precise snoop filter with Table B4.26, a home response policy |

Not modelled, by decision: Resource Planes and shared credits (`Num_RP_* = 1`; `*FLITRP`, `*SHAREDCRD`, `*LCRDSHV` are not bound), replicated channels, forwarding snoops (DCT), stash, atomics, DVM, MTE (every TagOp table variant is folded as `TagOp != Transfer` / `TagOp != Fetch`), RME, DMT / DWT, multi-request (MultiReq), C2C. `WriteDataCancel` is accepted by the Home (the write is dropped, the transaction completes) and checked by the monitor, but the RN-F BFM never sends it. The opcode enums still carry every value Table B13.12 to B13.16 names (atomics, stash, DVM, the Fwd snoops) so a flit decodes by name; what a BFM will *do* with a request is the set in `REQ_CLASS` on the protocol page. Reserved values are left out of the enums on purpose: `ReqOpcode(0x06)` raises.

## Why These Are Not GAXI Compositions

CHI has no READY. A flit moves when the transmitter spends an L-Credit the receiver granted on `LCRDV`, and the credit is usable the cycle after it was seen (B14.2.1.1). `FLITPEND` must be high the cycle before `FLITV` and nothing else permits a flit (B14.4). One `LINKACTIVEREQ`/`LINKACTIVEACK` pair per direction gates every channel of that direction (B14.5), and a link cannot deactivate until every credit has gone home as an LCrdReturn flit (B13.11). None of that is a valid/ready pair, so, like the CXS family, each BFM runs its own clocked loop (`CHIPort`) and shares the framework parts: `Packet` (as `CHIFlit`), `FieldConfig`, `FlexRandomizer` timing, and a `_recvQ` plus callbacks. The cycle rules themselves are pure-Python models in `chi_link.py`, stepped once per clock by the port, so a spec question is answerable without a simulator and the same objects serve a driver, a responder and a passive monitor.

## Components

| Class | Role |
|---|---|
| `CHIConfig`, `CHIIssue`, `NodeType` | Interface properties, rule-numbered legality, channel presence per node type, derived flit widths, `rtl_parameters()` |
| `CHIReqFlit`, `CHIRspFlit`, `CHISnpFlit`, `CHIDatFlit` | One flit per channel; `pack()` is the wire word; shared-slot aliases (`flit.stashnid` reads `returnnid`) |
| `LCreditTx`, `LCreditRx`, `TxChannel`, `RxChannel`, `TxLink`, `RxLink`, `LinkChecker` | Pure-Python per-cycle link models and the passive checker |
| `CHITransaction`, `Action`, `TxnIdPool`, `RequesterTracker`, `CompleterTracker` | One request's legal sequence; the Requester-side and Home-side bookkeeping |
| `RNCache`, `SnoopFilter`, `HomePolicy` | B4 cache states, the Home directory, the Resp an HN-F sends back |
| `CHIPort` | The clocked chassis: binding, credited channels, LINKACTIVE pair, SACTIVE, the drive / sample loop |
| `CHIRequestNode` | RN-F (or RN-I) BFM: issues requests, completes them, answers snoops from its cache |
| `CHIHome`, `CHIHomeNode`, `HomeOptions` | The home protocol (memory, snoop filter, completer tracker, flow choices) and one HN-F port serving one RN link from it |
| `CHIMonitor` | Passive: flits, link checks, transaction checks, peak credit counts |
| `create_chi_requester`, `create_chi_home`, `create_chi_monitor` | One-call construction; `cfg` may be keyword properties instead of a `CHIConfig` |

An SN-F `NodeType` exists for channel presence, but no BFM plays it: `CHIRequestNode` requires an RN type and `CHIHomeNode` an HN type.

## Timing Convention

Outputs change right after the rising edge and inputs are sampled at the falling edge, the APB / WB4 / CXS convention. A model `step()` runs at the rising edge of cycle n with the inputs sampled at the end of cycle n-1, and what it returns is driven during cycle n. The spec's rules fall out of that directly:

- `LCRDV` asserted in cycle n is sampled at the end of n and usable in n+1, never in n: "An L-Credit cannot be used in the same cycle as being received" (B14.2.1.1). Figure B14.1 has `LCRDV` in cycle 1 and `FLITV` in cycle 2, and the unit test reproduces it cycle for cycle.
- `FLITPEND` driven in cycle n permits `FLITV` in n+1 and nothing else does (B14.4).
- `LINKACTIVEACK` sampled at the end of cycle n puts the link in RUN in n+1.

During reset every output is deasserted (B14.1.3) and every model is returned to that state; queued flits are kept and go once the link is up again.

## Port Naming

The spec names signals from the node's own perspective: `TXREQFLITV` is what an RN drives, and a DUT names its pins from its own perspective too. So a BFM, whatever node it plays, always drives the DUT's `rx*` pins and samples its `tx*` pins. There is no side-selection argument: the binder asks the shared `SignalResolver` (`components/shared/signal_mapping_helper.py`) for the port kind across the link (`chi_hn_f_port` for an RN-F BFM, `chi_rn_f_port` for an HN-F BFM) and swaps tx/rx on every logical name. An RN-F BFM facing a Home-side DUT with ports `s_chi_rxreqflitv ...` binds with `prefix='s_chi_'` and nothing else, exactly as an AXI4 master binds with `prefix='s_axi_'`.

`prefix` and `bus_name` are tried with and without a trailing underscore over the spellings a port may use, so `s_chi_rxreqflitv`, `u0_rx_req_flitv`, `u0_rx_req_flit_v` and `RXREQFLITV` all bind without a `signal_map`. `signal_map={'txreqflit': 'my_req_bus'}` overrides any subset, keyed by the BFM-perspective name, and discovery resolves the rest; an unknown key is rejected. The flit signals of every channel the node type has are required and a missing one fails construction naming every spelling tried; LINKACTIVE and SACTIVE are optional on the DUT and required only when `CHIConfig.link_control` / `sactive` say so. `tests/unit/test_flat_signal_resolver.py` pins the spellings.

A loopback with no node of its own, such as `tests/sim/rtl/chi/chi_wires.sv`, names each side's pins the way the node across from it would: the `rn_` side looks like an HN-F port to the RN-F BFM (the RN drives `rn_rxreq*`), the `hn_` side looks like an RN-F port to the HN-F BFM.

Which signals are bound follows the node type (Table B13.1 and the B13.6 figures):

| Node type | TX channels | RX channels |
|---|---|---|
| RN-F, RN-D | REQ, RSP, DAT | RSP, DAT, SNP |
| RN-I | REQ, RSP, DAT | RSP, DAT |
| HN-F | RSP, DAT, SNP | REQ, RSP, DAT |
| HN-I | RSP, DAT | REQ, RSP, DAT |
| SN-F | RSP, DAT | REQ, DAT |

For each TX channel `tx<ch>flitpend`, `tx<ch>flitv`, `tx<ch>flit` are driven and `tx<ch>lcrdv` is read; for each RX channel `rx<ch>flitpend`, `rx<ch>flitv`, `rx<ch>flit` are read and `rx<ch>lcrdv` is driven. With `link_control=True`, `txlinkactivereq` and `rxlinkactiveack` are driven and `txlinkactiveack` and `rxlinkactivereq` are read; with `sactive=True`, `txsactive` is driven and `rxsactive` read. A missing signal fails construction with its name. Not bound: `*FLITRP`, `*SHAREDCRD`, `*LCRDSHV` (Resource Planes), and the monitor binds the flit, credit and LINKACTIVE signals only, never `txsactive` / `rxsactive`. With `link_control=False` both links are treated as permanently in RUN.

## Quick Start

From the loopback test: an RN-F and an HN-F BFM on either side of `chi_wires`, a monitor on each, then a write and a read.

```python
from CocoTBFramework.components.chi import (
    CHIConfig, HomeOptions, ReqOpcode, Size,
    create_chi_requester, create_chi_home, create_chi_monitor)

rn_cfg = CHIConfig(node_type='RN-F', data_width=128)
hn_cfg = CHIConfig(node_type='HN-F', data_width=128)
rn  = create_chi_requester(dut, "RN", "rn_", dut.clk, rn_cfg, node_id=1, home_id=0,
                           reset=dut.rst_n, seed=1)
hn  = create_chi_home(dut, "HN", "hn_", dut.clk, hn_cfg, rn_id=1, node_id=0,
                      options=HomeOptions(comp_delay=(0, 4)),
                      reset=dut.rst_n, seed=1)
mon_rn = create_chi_monitor(dut, "MonRN", "rn_", dut.clk, rn_cfg, reset=dut.rst_n)
mon_hn = create_chi_monitor(dut, "MonHN", "hn_", dut.clk, hn_cfg, reset=dut.rst_n)

data = bytes(range(64))
t = await rn.write(0x1000, data, opcode=ReqOpcode.WriteNoSnpFull)   # CompDBIDResp, data, done
assert t.status == 'done'
t = await rn.read(0x1000, opcode=ReqOpcode.ReadNoSnp)                # CompData x4 at DW 128
assert t.read_data() == data
t = await rn.read(0x1000, opcode=ReqOpcode.ReadShared)               # CompData then CompAck
assert t.compack_sent and rn.cache.state(0x1000) in ('UC', 'SC')

await rn.wait_tx_idle(); await hn.wait_tx_idle()
assert mon_rn.total_violations() == 0, mon_rn.all_violations()
assert mon_hn.max_credits['rxreq'] > 0                               # the credit pool was used
```

`read` / `write` / `dataless` / `writeback` issue and await; `issue(new_txn(...))` fires and `wait(txn)` collects later, which is how the random phase keeps up to six outstanding. `write` derives `Size` from `len(data)` (`Size.of` raises for a length that is not 1, 2, 4, 8, 16, 32 or 64). Several HN-F ports share one home by passing the same `home=` to `create_chi_home`; the home snoops an RN through the port registered under that RN's `rn_id`.

## Randomizer Keys

`CHIPort` takes a `FlexRandomizer`; these keys are read, each with its default `(bins, weights)`:

| Key | Meaning | Default |
|---|---|---|
| `flit_gap` | Idle cycles after each TX flit, per channel | 0 (w8), 1-2 (w1) |
| `lcrd_gap` | Cycles between credit grants, per RX channel | 0 (w12), 1-2 (w1) |
| `drain_gap` | Extra cycles the modelled RX buffer holds each flit (a slow consumer: credits run out and the transmitter stalls) | 0 (w10), 1-3 (w1) |
| `ack_delay` | Cycles from seeing `LINKACTIVEREQ` to raising `ACK` | 0 (w3), 1-4 (w1) |

`CHIPort` also takes `rx_buffer_depth` (slots backing the RX credits; default `max_lcredit`), `pend_mode` (`'exact'` or `'always'`, B14.4), `auto_link` and `idle_deactivate` (cycles of idle RUN before the TX link drops; default `None`, never). Those four are constructor arguments of `CHIRequestNode` / `CHIHomeNode` through `**port_kwargs`, and `create_chi_requester` / `create_chi_home` forward them by name.

## Monitor Checks

`CHIMonitor` watches one port from one node's perspective and never drives. Every protocol flit goes to `_recvQ` and the callbacks as a `CHIFlit` with `channel` and `start_time` set; `opcode_counts['<ch>.<Opcode>']` tallies them. Each kind is counted in `violations` and logged, never raised. `all_violations()` merges the link checker's counts under `link.<kind>`:

| Kind | Rule |
|---|---|
| `link.valid_without_pend` | `FLITV` without `FLITPEND` the cycle before (B14.4) |
| `link.valid_without_credit` | A flit with no usable credit; a credit is usable the cycle after `LCRDV` (B14.2.1.1) |
| `link.credit_overflow` | More than `max_lcredit` credits at a transmitter |
| `link.valid_not_run` | A flit outside RUN / DEACTIVATE (Table B14.2) |
| `link.credit_not_permitted` | `LCRDV` outside RUN (Table B14.3), except the first cycle of DEACTIVATE |
| `link.handshake` | A four-phase step out of order (B14.5), or a B14.6.3.4 ordering break between this port's `TXLINKACTIVEREQ` and `RXLINKACTIVEACK` |
| `link.ack_drop_with_credits` | An `ACK` fell while that direction's transmitter held credits (Table B14.3) |
| `link.lcrd_return_outside_deactivate` | An LCrdReturn flit on a link not in DEACTIVATE (B13.11) |
| `lcrd_return_txnid` | An LCrdReturn with TxnID != 0 (B13.11) |
| `txnid_reuse` | A REQ reusing the TxnID of an open request from the same SrcID (B2.4.2), unless it is the re-send after a RetryAck |
| `txn_fields` | A REQ that fails `CHITransaction.validate()` (ExpCompAck, PCrdType / AllowRetry, TxnID width) |
| `txn_unknown` | A RSP / DAT toward the requester whose TxnID matches no open request |
| `txn_sequence` | A response the transaction model rejects (CompAck before Comp, write data before a DBID, a second Comp, a reserved Resp encoding, ...), a CompAck or write data from the requester that matches no DBID still owing one, a second CompAck, or a write-data opcode that is not the Table B4.44 one for the request |
| `retry_resend` | A re-sent request before PCrdGrant, with AllowRetry = 1, with a PCrdType other than the granted one, or with a different opcode / address (B2.10) |
| `dbid_reuse` | A DBID handed to a requester while an earlier transaction to that requester still owes its CompAck or write data on it (B2.4.3) |
| `dataid` | Write data or snoop data with a DataID the transfer does not need, or the same DataID twice (B2.9.4) |
| `snoop_unknown` / `snoop_txnid_reuse` | A SnpResp / SnpRespData matching no outstanding snoop, or a snoop reusing an outstanding snoop's TxnID |

Transaction tracking (`track_transactions=True`) keys every REQ by (SrcID, TxnID) in a `RequesterTracker` per SrcID and feeds it each RSP / DAT toward the requester. The model says what a legal requester would owe next; the monitor then checks the wire shows it: every DBID that still owes a CompAck or write data is held until both arrive, and every snoop until its response. `unfinished()` lists what is still owed; call it at the end of a test and fail on a non-empty list, since no per-flit check can report a CompAck that never came (the loopback does, and a mutant RN that never sends CompAck is caught that way, plus `HN.timeout`). Completed transactions go to `transactions`. `max_credits[key]` (`'rxreq'`, `'txdat'`, ...) is the peak transmitter credit count the monitor modelled per channel, which is how a test proves a pool was exercised; the loopback verdict fails on a zero there.

The BFMs count on themselves too: `CHIPort.all_violations()` holds `valid_without_pend`, `lcrd_return_txnid`, `x_on_wire` (an X / Z on a control signal, or on a FLIT while FLITV is high; the flit is dropped rather than read as an LCrdReturn), `unsupported` (an opcode or state outside this family's scope arrived; the BFM counts it instead of crashing), the per-channel model counts (`req.credit_overflow`, `dat.valid_without_credit`), `txlink.ack_drop_with_credits`, and the node-level `txn_fields`, `txn_unknown`, `txn_sequence`; the HN adds `txn_unexpected`, `snoop_dataid`, `rn_id_mismatch` (a REQ whose SrcID is not the `rn_id` the port was registered under, so snoops to that RN could never match) and `timeout` (a CompAck, write data or snoop response the other side never sent within `HomeOptions.wait_timeout` cycles; the line lock is released so the test can finish and report). A reset seen on the wire drops every open transaction, snoop and event on every BFM and the monitor.

## Running the Tests

The unit tests need no simulator; the loopback needs Verilator through `cocotb_test`.

```bash
cd RTLDesignSherpa-DV-dev
pytest tests/unit/test_chi_*.py                       # config, flits, opcodes, link, transaction, cache model
REG_LEVEL=GATE pytest tests/sim/chi/test_chi_loopback.py
```

`REG_LEVEL` picks the parameter grid: `GATE` is one cell (DW 128, basic), `FUNC` (the default) is three cells (DW 128 / 256 / 512 with the home's separate-response, copyback-Comp and retry rates at 0, 0.5 and 1.0), `FULL` is the product of DW x read_sep x write_sep x copyback_comp x retry_rate x level, 96 cells. Each cell exports `TEST_LEVEL` (`basic` / `medium` / `full`: 40 / 150 / 500 random operations), `TEST_DATA_WIDTH`, `TEST_READ_SEP`, `TEST_WRITE_SEP`, `TEST_COPYBACK_COMP` and `TEST_RETRY_RATE` to the cocotb side. `SEED` fixes the seed (otherwise random, and logged), `WAVES=1` dumps waves. Builds land in `tests/sim/local_sim_build/<cell>` and results in `tests/sim/logs/results_<cell>.xml`.

The loopback runs four phases (non-coherent writes and reads including a 16-byte partial, coherent reads with the cache model and a WriteBackFull, two direct snoops through `hn.home.snoop()`, then the random mix) and its verdict needs zero violations on both monitors and both BFMs, every phase count above zero, and a non-zero peak credit count, so a phase that silently did nothing cannot pass.

## Used By

No RTL consumer yet; the family is exercised BFM-to-BFM through `tests/sim/rtl/chi/chi_wires.sv`, whose parameters `REQ_W` / `RSP_W` / `SNP_W` / `DAT_W` the runner sets from `CHIConfig.req_flit_width` and friends.
