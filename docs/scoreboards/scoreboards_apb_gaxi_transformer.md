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

The transformer above is stateless—it converts one packet and hands it back. The adapters wrap it with the bookkeeping a live testbench needs: they own a transformer, forward converted transactions to a master component, and keep running counts so you can ask how the bridge behaved after the fact.

### APBGAXIAdapterBase

Base class for the adapters—everything the concrete adapters share lives here.

```python
class APBGAXIAdapterBase:
    def __init__(self, transformer, field_config=None, log=None)
```

**Parameters:**
- `transformer`: the `APBtoGAXITransformer` instance doing the actual conversion
- `field_config`: field configuration to use (defaults to the transformer's `gaxi_field_config` when omitted)
- `log`: logger (defaults to the transformer's logger when omitted)

**What it holds:**
- `transaction_count`, `error_count`, `total_latency`: running statistics, all starting at zero
- `transformer`, `field_config`, `log`: the shared plumbing the subclasses reach for

**Methods:**

#### `reset_statistics()`
Zero the three counters (`transaction_count`, `error_count`, `total_latency`). Use it between test phases.

#### `get_average_latency()`
Return `total_latency / transaction_count`, or `0` if nothing has been processed yet.

### APBtoGAXIAdapter

Takes APB transactions in, sends GAXI packets out. Subclass of `APBGAXIAdapterBase`.

```python
class APBtoGAXIAdapter(APBGAXIAdapterBase):
    def __init__(self, transformer, gaxi_master, field_config=None, log=None)
```

**Parameters:**
- `transformer`: the `APBtoGAXITransformer` instance
- `gaxi_master`: the GAXI master the converted packets get sent to
- `field_config`: field configuration (defaults to the transformer's)
- `log`: logger (defaults to the transformer's)

Beyond the base state, it keeps a `pending_transactions` dict keyed by address, so the originating APB transaction can be looked up while its GAXI packet is in flight.

#### `async process_transaction(apb_transaction)`
Convert an APB transaction to a GAXI packet and push it through the GAXI master.

**Parameters:**
- `apb_transaction`: the APB transaction to process

**Returns:**
- `GAXIPacket`: the packet that was sent to the master

Under the hood it calls `transformer.apb_to_gaxi()`, records the transaction in `pending_transactions` under its address, bumps `transaction_count`, then `await`s `gaxi_master.send(packet)`.

### GAXItoAPBAdapter

The other direction: GAXI packets in, APB transactions out. Subclass of `APBGAXIAdapterBase`.

```python
class GAXItoAPBAdapter(APBGAXIAdapterBase):
    def __init__(self, transformer, apb_master, apb_transaction_class,
                 field_config=None, log=None)
```

**Parameters:**
- `transformer`: the `APBtoGAXITransformer` instance
- `apb_master`: the APB master the converted transactions get sent to
- `apb_transaction_class`: the class used to build APB transactions
- `field_config`: field configuration (defaults to the transformer's)
- `log`: logger (defaults to the transformer's)

It keeps a `pending_packets` dict keyed by address, mirroring the forward adapter.

#### `async process_packet(gaxi_packet)`
Convert a GAXI packet to an APB transaction and push it through the APB master.

**Parameters:**
- `gaxi_packet`: the GAXI packet to process

**Returns:**
- `APBTransaction`: the transaction that was sent to the master

It calls `transformer.gaxi_to_apb(gaxi_packet, apb_transaction_class)`, records the packet in `pending_packets`, bumps `transaction_count`, then `await`s `apb_master.send(transaction)`.

### `create_apb_gaxi_adapters(...)`

A factory for the common case: you want both directions wired up against a shared transformer.

```python
def create_apb_gaxi_adapters(apb_master, gaxi_master,
                             apb_transaction_class, gaxi_field_config,
                             log=None)
```

**Parameters:**
- `apb_master`: APB master for outgoing APB transactions
- `gaxi_master`: GAXI master for outgoing GAXI packets
- `apb_transaction_class`: class used to build APB transactions
- `gaxi_field_config`: field configuration for GAXI packets
- `log`: logger instance

**Returns:**
- `tuple` of `(APBtoGAXIAdapter, GAXItoAPBAdapter)`—both sharing one freshly built `APBtoGAXITransformer`.

```python
from CocoTBFramework.scoreboards.apb_gaxi_transformer import create_apb_gaxi_adapters

# Build both adapters against a shared transformer
apb_to_gaxi, gaxi_to_apb = create_apb_gaxi_adapters(
    apb_master=apb_master,
    gaxi_master=gaxi_master,
    apb_transaction_class=APBPacket,
    gaxi_field_config=field_config,
    log=logger,
)

# APB in → GAXI out
gaxi_packet = await apb_to_gaxi.process_transaction(apb_write)

# GAXI in → APB out
apb_transaction = await gaxi_to_apb.process_packet(gaxi_response)

# Check how the bridge behaved
print(f"Forward transactions: {apb_to_gaxi.transaction_count}")
print(f"Average latency: {apb_to_gaxi.get_average_latency()} ns")
```
