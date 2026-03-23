# AXI5 Interface Classes

The AXI5 interface classes provide high-level master and slave interfaces for AXI5 protocol operations. Each class composes GAXI channel objects and coordinates transactions across related channels with full support for AXI5-specific features.

## AXI5MasterRead

Manages read address requests (AR) and read data responses (R) with full AXI5 signal support.

### Class Signature

```python
class AXI5MasterRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `clock` | Signal | Clock signal | (required) |
| `prefix` | str | Signal name prefix (e.g., `"m_axi_"`) | `""` |
| `log` | Logger | Logger instance | `None` |
| `ifc_name` | str | Interface name suffix for debug | `""` |
| `data_width` | int | Data bus width in bits | `32` |
| `id_width` | int | ID field width in bits | `8` |
| `addr_width` | int | Address bus width in bits | `32` |
| `user_width` | int | User signal width in bits | `1` |
| `nsaid_width` | int | NSAID field width in bits | `4` |
| `mpam_width` | int | MPAM field width in bits | `11` |
| `mecid_width` | int | MECID field width in bits | `16` |
| `tagop_width` | int | TAGOP field width in bits | `2` |
| `tag_width` | int | Single tag width in bits | `4` |
| `chunknum_width` | int | Chunk number width in bits | `4` |
| `multi_sig` | bool | Use individual signals per field | `True` |
| `timeout_cycles` | int | Transaction timeout in clock cycles | `5000` |

### Key Methods

#### `read_transaction(address, burst_len=1, **transaction_kwargs) -> List[Dict]`

Perform a high-level read transaction with AXI5 features.

**Parameters**:

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `address` | int | Read address | (required) |
| `burst_len` | int | Number of data beats | `1` |
| `id` | int | Transaction ID | `0` |
| `size` | int | Burst size encoding | `2` |
| `burst` | int | Burst type (0=FIXED, 1=INCR, 2=WRAP) | `1` |
| `nsaid` | int | Non-secure access ID | `0` |
| `trace` | int | Enable transaction tracing | `0` |
| `mpam` | int | Memory partitioning info | `0` |
| `mecid` | int | Memory encryption context | `0` |
| `unique` | int | Unique/exclusive access | `0` |
| `chunken` | int | Enable chunking | `0` |
| `tagop` | int | Tag operation type | `0` |

**Returns**: List of response dictionaries, each containing:
- `data`, `resp`, `last`, `id` -- standard AXI fields
- `trace`, `poison`, `chunkv`, `chunknum`, `chunkstrb`, `tag`, `tagmatch` -- AXI5 fields

#### `single_read(address, **kwargs) -> int`

Convenience method for a single-beat read. Returns the data value directly.

#### `create_ar_packet(**kwargs)`

Create an AR packet with the current field configuration.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `ar_channel` | GAXIMaster | AR channel master component |
| `r_channel` | GAXISlave | R channel slave component |

### Usage Examples

```python
# Example 1: Simple single read
master_rd = AXI5MasterRead(dut, clk, prefix="m_axi_", data_width=32)
data = await master_rd.single_read(0x1000, id=1)

# Example 2: Burst read with security context
responses = await master_rd.read_transaction(
    address=0x2000, burst_len=4,
    id=2, nsaid=1, trace=1, tagop=1
)
for resp in responses:
    print(f"data=0x{resp['data']:X}, poison={resp['poison']}")

# Example 3: Chunked read for wide data bus
responses = await master_rd.read_transaction(
    address=0x4000, burst_len=8,
    id=3, chunken=1
)
```

---

## AXI5MasterWrite

Manages write address requests (AW), write data (W), and write responses (B) with full AXI5 signal support including atomic operations and memory tagging.

### Class Signature

```python
class AXI5MasterWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `clock` | Signal | Clock signal | (required) |
| `prefix` | str | Signal name prefix | `""` |
| `log` | Logger | Logger instance | `None` |
| `ifc_name` | str | Interface name suffix | `""` |
| `data_width` | int | Data bus width in bits | `32` |
| `id_width` | int | ID field width in bits | `8` |
| `addr_width` | int | Address bus width in bits | `32` |
| `user_width` | int | User signal width in bits | `1` |
| `nsaid_width` | int | NSAID field width in bits | `4` |
| `mpam_width` | int | MPAM field width in bits | `11` |
| `mecid_width` | int | MECID field width in bits | `16` |
| `atop_width` | int | ATOP field width in bits | `6` |
| `tagop_width` | int | TAGOP field width in bits | `2` |
| `tag_width` | int | Single tag width in bits | `4` |
| `multi_sig` | bool | Use individual signals per field | `True` |
| `timeout_cycles` | int | Transaction timeout in clock cycles | `5000` |

### Key Methods

#### `write_transaction(address, data, burst_len=None, **transaction_kwargs) -> Dict`

Perform a high-level write transaction with AXI5 features.

**Parameters**:

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `address` | int | Write address | (required) |
| `data` | int or List[int] | Write data (single or burst) | (required) |
| `burst_len` | int or None | Burst length (auto-detected if None) | `None` |
| `id` | int | Transaction ID | `0` |
| `atop` | int | Atomic operation type | `0` |
| `nsaid` | int | Non-secure access ID | `0` |
| `trace` | int | Enable transaction tracing | `0` |
| `tagop` | int | Tag operation type | `0` |
| `tag` | int | Memory tag (AW channel) | `0` |
| `poison` | int | Poison indicator (W channel) | `0` |
| `tagupdate` | int | Tag update indicators (W channel) | `0` |

**Returns**: Response dictionary with `success`, `response`, `id`, `trace`, `tag`, `tagmatch`.

#### `single_write(address, data, **kwargs) -> Dict`

Convenience method for a single-beat write.

#### `atomic_operation(address, data, atop, **kwargs) -> Dict`

Perform an atomic operation. Sets `atop` and forces single-beat transfer.

**ATOP Encoding**:
- `0x10` -- AtomicStore
- `0x20` -- AtomicLoad
- `0x30` -- AtomicSwap
- `0x31` -- AtomicCompare

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `aw_channel` | GAXIMaster | AW channel master component |
| `w_channel` | GAXIMaster | W channel master component |
| `b_channel` | GAXISlave | B channel slave component |

### Usage Examples

```python
# Example 1: Single write with tracing
master_wr = AXI5MasterWrite(dut, clk, prefix="m_axi_", data_width=64)
result = await master_wr.single_write(0x1000, 0xDEADBEEF, id=1, trace=1)

# Example 2: Atomic swap operation
result = await master_wr.atomic_operation(
    address=0x2000, data=0xCAFEBABE, atop=0x30, id=2
)

# Example 3: Burst write with memory tagging
result = await master_wr.write_transaction(
    address=0x3000,
    data=[0x11111111, 0x22222222, 0x33333333, 0x44444444],
    id=3, tagop=2, tag=0xA, tagupdate=0x1
)
```

---

## AXI5SlaveRead

Handles read requests from masters and generates appropriate responses with full AXI5 signal support. Supports out-of-order response reordering.

### Class Signature

```python
class AXI5SlaveRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `clock` | Signal | Clock signal | (required) |
| `prefix` | str | Signal name prefix | `""` |
| `log` | Logger | Logger instance | `None` |
| `ifc_name` | str | Interface name suffix | `""` |
| `data_width` | int | Data bus width in bits | `32` |
| `id_width` | int | ID field width in bits | `8` |
| `addr_width` | int | Address bus width in bits | `32` |
| `user_width` | int | User signal width in bits | `1` |
| `nsaid_width` | int | NSAID field width in bits | `4` |
| `mpam_width` | int | MPAM field width in bits | `11` |
| `mecid_width` | int | MECID field width in bits | `16` |
| `tagop_width` | int | TAGOP field width in bits | `2` |
| `tag_width` | int | Single tag width in bits | `4` |
| `chunknum_width` | int | Chunk number width in bits | `4` |
| `multi_sig` | bool | Use individual signals per field | `True` |
| `memory_model` | object | Memory model for data sourcing | `None` |
| `base_addr` | int | Base address offset | `0` |
| `response_delay` | int | Response delay in clock cycles | `1` |
| `enable_ooo` | bool | Enable out-of-order responses | `False` |
| `ooo_config` | dict | Out-of-order configuration | See below |

**OOO Configuration Dict**:
```python
{
    'mode': 'random',            # 'random' or 'deterministic'
    'reorder_probability': 0.3,  # Probability of reordering
    'min_delay_cycles': 1,       # Minimum reorder delay
    'max_delay_cycles': 50,      # Maximum reorder delay
    'pattern': None              # Sequence order for deterministic mode
}
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `ar_channel` | GAXISlave | AR channel slave component |
| `r_channel` | GAXIMaster | R channel master component |

### Usage Examples

```python
# Example 1: Basic slave read with memory model
slave_rd = AXI5SlaveRead(
    dut, clk, prefix="s_axi_",
    memory_model=memory, data_width=32
)

# Example 2: Slave with out-of-order responses
slave_rd = AXI5SlaveRead(
    dut, clk, prefix="s_axi_",
    memory_model=memory,
    enable_ooo=True,
    ooo_config={
        'mode': 'random',
        'reorder_probability': 0.3,
        'min_delay_cycles': 2,
        'max_delay_cycles': 20
    }
)
```

---

## AXI5SlaveWrite

Handles write requests from masters and generates appropriate responses with full AXI5 signal support.

### Class Signature

```python
class AXI5SlaveWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

### Constructor Parameters

The constructor parameters mirror `AXI5SlaveRead` with the addition of:

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `atop_width` | int | ATOP field width in bits | `6` |

All other parameters are identical to `AXI5SlaveRead`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `aw_channel` | GAXISlave | AW channel slave component |
| `w_channel` | GAXISlave | W channel slave component |
| `b_channel` | GAXIMaster | B channel master component |

### Usage Examples

```python
# Example 1: Basic slave write
slave_wr = AXI5SlaveWrite(
    dut, clk, prefix="s_axi_",
    memory_model=memory, data_width=32
)

# Example 2: Slave write with OOO and security features
slave_wr = AXI5SlaveWrite(
    dut, clk, prefix="s_axi_",
    memory_model=memory,
    data_width=64,
    nsaid_width=4,
    mpam_width=11,
    mecid_width=16,
    enable_ooo=True
)
```

---

## Factory Functions

Factory functions provide the recommended way to create AXI5 interface components. They return dictionaries containing the interface and its constituent channel components.

### `create_axi5_master_rd(dut, clock, prefix, log, ifc_name, **kwargs) -> Dict`

Returns `{'AR': ar_channel, 'R': r_channel, 'interface': AXI5MasterRead}`.

### `create_axi5_master_wr(dut, clock, prefix, log, ifc_name, **kwargs) -> Dict`

Returns `{'AW': aw_channel, 'W': w_channel, 'B': b_channel, 'interface': AXI5MasterWrite}`.

### `create_axi5_slave_rd(dut, clock, prefix, log, ifc_name, **kwargs) -> Dict`

Returns `{'AR': ar_channel, 'R': r_channel, 'interface': AXI5SlaveRead}`.

### `create_axi5_slave_wr(dut, clock, prefix, log, ifc_name, **kwargs) -> Dict`

Returns `{'AW': aw_channel, 'W': w_channel, 'B': b_channel, 'interface': AXI5SlaveWrite}`.

### `create_axi5_master_interface(dut, clock, prefix, log, **kwargs) -> Tuple`

Returns `(AXI5MasterWrite, AXI5MasterRead)` -- both read and write master interfaces.

### `create_axi5_slave_interface(dut, clock, prefix, log, **kwargs) -> Tuple`

Returns `(AXI5SlaveWrite, AXI5SlaveRead)` -- both read and write slave interfaces.

### `create_complete_axi5_testbench_components(dut, clock, master_prefix, slave_prefix, log, **kwargs) -> Dict`

Creates a complete set of master and slave components. Returns a dictionary with keys `'master_write'`, `'master_read'`, `'slave_write'`, `'slave_read'` (each present only if the corresponding DUT signals exist).

### Usage Example

```python
from CocoTBFramework.components.axi5 import (
    create_axi5_master_rd,
    create_axi5_master_wr,
    create_complete_axi5_testbench_components
)

# Individual interface creation
rd_components = create_axi5_master_rd(
    dut, clk, prefix="m_axi_", log=self.log,
    data_width=64, id_width=4
)
master_read = rd_components['interface']

# Complete testbench
all_components = create_complete_axi5_testbench_components(
    dut, clk,
    master_prefix="m_axi_",
    slave_prefix="s_axi_",
    data_width=64, id_width=4
)
```
