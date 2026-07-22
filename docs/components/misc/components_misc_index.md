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

# Misc Components Index

Everything that doesn't belong to a protocol family lands here. At the moment that's the arbiter monitor — arbitration lives inside buses, schedulers, and DMA engines rather than on a standalone interface, so it gets its own corner of the tree.

> **Note:** These modules live under `src/CocoTBFramework/components/shared/` (e.g. `arbiter_monitor.py`); there is no separate `misc` package in the source tree.

## Overview
- [**Overview**](components_misc_overview.md) - What lives here and how these components are meant to be used

## Components

### Monitoring Components
- [**arbiter_monitor.py**](components_misc_arbiter_monitor.md) - Arbiter monitor for round-robin and weighted round-robin designs, with fairness scoring and pattern analysis

## Navigation
- [**Back to Components**](../components_index.md) - Return to main components index
- [**Back to CocoTBFramework**](../components_index.md) - Return to framework root
