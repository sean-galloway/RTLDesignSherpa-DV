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

**[← Back to Components Index](../components_index.md)** | **[CocoTBFramework Index](../../index.md)**

# CHI Components

CHI is Arm's Coherent Hub Interface (*AMBA CHI Architecture Specification*, Arm IHI 0050, Issue H). This family is a Request Node BFM (RN-F / RN-I), a Home Node BFM (HN-F, several ports sharing one memory and snoop filter), and a passive monitor, built on pure-Python models of the link layer (L-Credits, FLITPEND, LINKACTIVE, LCrdReturn), the transaction flows (reads, dataless, immediate and CopyBack writes, retry) and the cache-state tables of chapter B4. Issue H only, one Resource Plane, no replicated channels; the explicit not-modelled list is on the overview page. Because every link rule lives in a model the BFMs merely step, the same objects serve the driver, the responder and the monitor, and every rule is unit-tested without a simulator.

## Documentation Structure

- **[Overview](components_chi_overview.md)** - Scope, why these are not GAXI compositions, the component table, timing and port naming, quick start, randomizer keys, monitor checks, how to run the tests
- **[Config and Flits](components_chi_config_flits.md)** - `CHIConfig` and its rules, the derived flit widths, the four flit layouts bit 0 first, pack/unpack, opcodes and field encodings
- **[Protocol Models](components_chi_protocol.md)** - The link-layer models, the transaction model and trackers, the cache model, snoop filter and home policy, and what the RN-F and HN-F BFMs do with them

## Components

| Class | Page |
|---|---|
| `CHIConfig`, `CHIIssue`, `NodeType`, `CONFIG_RULES` | Config and Flits |
| `CHIReqFlit`, `CHIRspFlit`, `CHISnpFlit`, `CHIDatFlit`, `ALIASES` | Config and Flits |
| `ReqOpcode`, `RspOpcode`, `SnpOpcode`, `DatOpcode`, `Size`, `MemAttr`, `Order`, `RespErr`, `Resp`, `FwdState` | Config and Flits |
| `LCreditTx`, `LCreditRx`, `TxChannel`, `RxChannel`, `TxLink`, `RxLink`, `LinkChecker` | Protocol Models |
| `CHITransaction`, `Action`, `TxnIdPool`, `RequesterTracker`, `CompleterTracker` | Protocol Models |
| `RNCache`, `SnoopFilter`, `HomePolicy`, `SnoopResponse`, `HomeDecision` | Protocol Models |
| `CHIPort`, `CHIRequestNode`, `CHIHome`, `CHIHomeNode`, `HomeOptions`, `CHIMonitor` | Overview, Protocol Models |
| `create_chi_requester`, `create_chi_home`, `create_chi_monitor` | Overview |

## Used By

`tests/sim/chi/test_chi_loopback.py` runs an RN-F BFM against an HN-F BFM through `tests/sim/rtl/chi/chi_wires.sv` (wires only), with a monitor on each side. The unit tests are `tests/unit/test_chi_*.py`.
