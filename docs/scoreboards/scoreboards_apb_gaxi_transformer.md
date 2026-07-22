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

# apb_gaxi_transformer.py

When a testbench has APB on one side and GAXI on the other, something has to translate before a comparison means anything. This module is that something: bidirectional APB ↔ GAXI conversion, plus adapter classes that keep the plumbing out of the rest of the bench.

## Overview

- **Bidirectional Transformation**: APB → GAXI and GAXI → APB
- **Field Mapping**: configurable correspondence between the two protocols' fields
- **Timing Preservation**: transaction timestamps survive the trip across
- **Adapter Framework**: high-level wrappers for hooking conversion into master components
- **Performance Tracking**: transformation counts and latency analysis

## Classes

### APBtoGAXITransformer

The converter itself. One instance handles both directions.

> **This module is the canonical implementation.** The same-named class in
> `scoreboards.apb_scoreboard` is a thin subclass kept around for backward
> compatibility: it holds on to the older `(gaxi_field_config, packet_class, log)`
> constructor and a `transform()` that returns a list, while inheriting
> `apb_to_gaxi()` / `gaxi_to_apb()` from this class. New code should import from
> `apb_gaxi_transformer`.

```python
class APBtoGAXITransformer:
    def __init__(self, gaxi_field_config, gaxi_packet_class=GAXIPacket, log=None)
```

**Parameters:**
- `gaxi_field_config`: GAXI field configuration used to build packets
- `gaxi_packet_class`: packet class to instantiate (default: GAXIPacket)
- `log`: logger for transformation debugging

**Key Features:**
- Field mapping between the APB and GAXI formats
- Data handling that respects transaction direction
- Timing information carried across the conversion
- Errors logged, not swallowed

## Core Transformation Methods

### APB to GAXI Conversion

#### `apb_to_gaxi(apb_transaction)`
Turn an APB transaction into a GAXI packet.

**Parameters:**
- `apb_transaction`: the APB transaction to convert

**Returns:**
- `GAXIPacket`: the converted packet

**Field Mapping:**
- `apb.paddr` → `gaxi.addr`: address
- `apb.pwdata/prdata` → `gaxi.data`: data, chosen by direction
- `apb.pstrb` → `gaxi.strb`: write strobe (writes only)
- `apb.direction` → `gaxi.cmd`: command type (1 = write, 0 = read)

```python
# APB write transaction transformation
apb_write = APBPacket()
apb_write.direction = 'WRITE'
apb_write.paddr = 0x1000
apb_write.pwdata = 0xDEADBEEF
apb_write.pstrb = 0xF

gaxi_packet = transformer.apb_to_gaxi(apb_write)
# Result: gaxi_packet.addr=0x1000, gaxi_packet.data=0xDEADBEEF, gaxi_packet.cmd=1
```

### GAXI to APB Conversion

#### `gaxi_to_apb(gaxi_packet, apb_transaction_class)`
The reverse trip: GAXI packet to APB transaction.

**Parameters:**
- `gaxi_packet`: the GAXI packet to convert
- `apb_transaction_class`: APB class to instantiate

**Returns:**
- `APBTransaction`: the converted transaction

**Field Mapping:**
- `gaxi.addr` → `apb.paddr`: address
- `gaxi.data` → `apb.pwdata/prdata`: data, chosen by command type
- `gaxi.strb` → `apb.pstrb`: write strobe (when present)
- `gaxi.cmd` → `apb.direction`: 1 becomes WRITE, 0 becomes READ

```python
# GAXI packet transformation
gaxi_read = GAXIPacket(field_config)
gaxi_read.addr = 0x2000
gaxi_read.data = 0x12345678
gaxi_read.cmd = 0  # Read

apb_transaction = transformer.gaxi_to_apb(gaxi_read, APBPacket)
# Result: apb_transaction.direction='READ', apb_transaction.paddr=0x2000, apb_transaction.prdata=0x12345678
```

## Adapter Framework

### APBGAXIAdapterBase

Base class for the adapters—everything the concrete adapters share lives here.

```python
class APBGAXIAdapterBase:
    def __init__(self, transformer, field_config=None, log=None)
```

**
