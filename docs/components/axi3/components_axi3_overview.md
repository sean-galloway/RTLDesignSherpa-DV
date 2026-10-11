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

# AXI3 Components Overview

The AXI3 components are a standalone protocol family in this framework. They share the same GAXI infrastructure as AXI4/AXI5, but encode the AXI3 protocol deltas rather than inheriting from AXI4, so the differences are visible and enforced.

## Protocol Deltas from AXI4

- **4-bit AWLEN/ARLEN** — bursts are 1-16 beats, not 1-256.
- **2-bit AWLOCK/ARLOCK** — normal, exclusive, and locked accesses.
- **No QoS or REGION** — these AXI4 sideband signals do not exist in AXI3.
- **WID on the W channel** — write-data interleaving by ID is legal in AXI3.

## Components

- **AXI3MasterRead** — drives AR requests and receives R responses.
- **AXI3MasterWrite** — drives AW and W requests and receives B responses. It sets `WID = AWID` and does not interleave write data.
- **AXI3SlaveRead** — receives AR requests and generates R responses.
- **AXI3SlaveWrite** — receives AW and W requests and generates B responses. It demuxes W beats by `WID`, so it can accept interleaved write data from external masters.

## Factory Functions

```python
from CocoTBFramework.components.axi3 import (
    create_axi3_master_rd,
    create_axi3_master_wr,
    create_axi3_slave_rd,
    create_axi3_slave_wr,
)

master_read = create_axi3_master_rd(dut, clock, "m_axi_", log=dut._log)
master_write = create_axi3_master_wr(dut, clock, "m_axi_", log=dut._log)
slave_read = create_axi3_slave_rd(dut, clock, "s_axi_", log=dut._log)
slave_write = create_axi3_slave_wr(dut, clock, "s_axi_", log=dut._log)
```

## Packet Construction

```python
from CocoTBFramework.components.axi3 import AXI3Packet

aw = AXI3Packet.create_aw_packet(id=1, addr=0x1000, len=3, size=2, burst=1)
w = AXI3Packet.create_w_packet(id=1, data=0xDEADBEEF, last=1)
ar = AXI3Packet.create_ar_packet(id=2, addr=0x2000, len=7)
r = AXI3Packet.create_r_packet(id=2, data=0x12345678, resp=0, last=1)
```

## Field Configuration

```python
from CocoTBFramework.components.axi3 import AXI3FieldConfigHelper

aw_cfg = AXI3FieldConfigHelper.create_aw_field_config(id_width=4, addr_width=32)
assert aw_cfg.get_field('len').bits == 4
assert aw_cfg.get_field('lock').bits == 2
```

AXI3 lives in `src/CocoTBFramework/components/axi3/` and is tracked as issue #87.
