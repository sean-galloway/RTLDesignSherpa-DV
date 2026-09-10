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

# Wishbone B4 Components Index

The Wishbone B4 (pipelined) family: a master, a slave over a memory model, a monitor with the protocol checks, a packet class, sequences for describing traffic, and the factories that wire them up.

## Overview
- [**Overview**](components_wb4_overview.md) - What the family covers, how it differs from a GAXI composition, timing convention

## Core Components
- [**wb4_components.py**](components_wb4_wb4_components.md) - `WB4Monitor`, `WB4Slave`, `WB4Master` on the cocotb_bus chassis
- [**wb4_packet.py**](components_wb4_wb4_packet.md) - `WB4Packet`: one request and its termination
- [**wb4_sequence.py**](components_wb4_wb4_sequence.md) - `WB4Sequence`: the traffic axis, with address windows for the ERR/RTY ranges
- **wb4_factories.py** - `create_wb4_master` / `create_wb4_slave` / `create_wb4_monitor`
- **shared/wb4_common.py** - signal sets, data-name aliases, the status encoding

## Navigation
- [**Back to Components**](../components_index.md)
- [**Back to CocoTBFramework**](../../index.md)
