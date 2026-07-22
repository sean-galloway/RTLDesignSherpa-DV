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

# APB Components Index

Everything APB lives in this directory: the protocol BFMs, the packet and transaction layer, sequence generation, and the factory helpers that wire it all together.

## Overview
- [**Overview**](components_apb_overview.md) - Architecture, protocol coverage, and usage patterns for the APB family — start here

## Core Components

### Protocol Implementation
- [**apb_components.py**](components_apb_apb_components.md) - APB Monitor, Master, and Slave — the signal-level core
- [**apb_packet.py**](components_apb_apb_packet.md) - APB packet and transaction classes, with constrained randomization
- [**apb_sequence.py**](components_apb_apb_sequence.md) - List-driven test pattern generation with packet assembly

### Factory Functions & Utilities
- **apb_factories.py** - One-call creation and configuration of APB components *(documentation planned)*

## Navigation
- [**Back to Components**](../components_index.md) - Return to main components index
- [**Back to CocoTBFramework**](../components_index.md) - Return to main framework index

---
