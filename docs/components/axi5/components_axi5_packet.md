# AXI5Packet Class

The `AXI5Packet` class extends the base `Packet` class with AXI5-specific functionality. It uses generic field names that match the field configuration and supports all AXI5-specific features including atomic operations, memory tagging, chunked transfers, and poison indicators.

## Key Differences from AXI4

- **Removed fields**: `region` (ARREGION/AWREGION)
- **Added fields**: `atop`, `nsaid`, `trace`, `mpam`, `mecid`, `unique`, `tagop`, `tag`, `chunken`, `chunkv`, `chunknum`, `chunkstrb`, `poison`, `tagupdate`, `tagmatch`
- **Channel detection**: Uses AXI5-specific field presence (e.g., `atop` for AW, `chunken` for AR) to determine channel type
- **Protocol validation**: Includes AXI5-specific validation for ATOP encoding, TAGOP values, and chunk rules

## Class Signature

```python
class AXI5Packet(Packet):
    def __init__(self, field_config, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `field_config` | FieldConfig | Field configuration for the specific AXI5 channel | (required) |
| `**kwargs` | Any | Initial field values using generic names (`id`, `addr`, `data`, etc.) | -- |

## Class Methods (Packet Factories)

### `create_aw_packet(id_width, addr_width, user_width, data_width, **field_values) -> AXI5Packet`

Create a Write Address (AW) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `addr_width` | int | Width of ADDR field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `data_width` | int | Data width for tag calculation | `32` |
| `**field_values` | Any | AW field values (`id`, `addr`, `len`, `atop`, `tagop`, etc.) | -- |

### `create_w_packet(data_width, user_width, **field_values) -> AXI5Packet`

Create a Write Data (W) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data_width` | int | Width of DATA field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | W field values (`data`, `last`, `strb`, `poison`, `tag`, `tagupdate`) | -- |

### `create_b_packet(id_width, user_width, data_width, **field_values) -> AXI5Packet`

Create a Write Response (B) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `user_width` | int | Width of USER field | `1` |
| `data_width` | int | Data width for tag calculation | `32` |
| `**field_values` | Any | B field values (`id`, `resp`, `trace`, `tag`, `tagmatch`) | -- |

### `create_ar_packet(id_width, addr_width, user_width, **field_values) -> AXI5Packet`

Create a Read Address (AR) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `addr_width` | int | Width of ADDR field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | AR field values (`id`, `addr`, `len`, `chunken`, `tagop`, etc.) | -- |

### `create_r_packet(id_width, data_width, user_width, **field_values) -> AXI5Packet`

Create a Read Data (R) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `data_width` | int | Width of DATA field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | R field values (`id`, `data`, `resp`, `last`, `poison`, `chunkv`, `chunknum`, etc.) | -- |

## Instance Methods

### `get_channel_type() -> str`

Determine which AXI5 channel this packet belongs to based on field presence.

**Returns**: `'AW'`, `'W'`, `'B'`, `'AR'`, `'R'`, or `'UNKNOWN'`

### `validate_axi5_protocol() -> Tuple[bool, str]`

Validate the packet against AXI5 protocol rules.

**Checks performed**:
- Burst length range (0-255)
- Burst size range (0-7)
- Burst type validity (0, 1, 2)
- ATOP encoding validity (AW channel)
- TAGOP range (0-3)
- Response code validity (B, R channels)
- Chunk field consistency (R channel)
- WLAST / RLAST presence

**Returns**: Tuple of `(is_valid, error_message)` where `error_message` is empty if valid.

### `get_burst_info() -> Dict[str, Any]`

Get burst information from address packets (AW/AR).

**Returns**: Dictionary with keys: `burst_type`, `burst_length`, `burst_size`, `bytes_per_beat`, `total_bytes`, `address`. Returns empty dict for non-address packets.

### `get_response_info() -> Dict[str, Any]`

Get response information from response packets (B/R).

**Returns**: Dictionary with keys: `response_code`, `response_name`, `is_error`, `is_exclusive`, `tagmatch`. For R channel, also includes `is_last`, `poison`, `chunkv`, `chunknum`. For B channel, also includes `trace`.

### `get_axi5_features() -> Dict[str, Any]`

Get AXI5-specific feature information from the packet.

**Returns**: Dictionary with feature status including:
- `is_atomic`, `atomic_type` -- atomic operation info
- `tagop`, `tag`, `tagmatch`, `tagupdate` -- MTE info
- `nsaid`, `mpam`, `mecid` -- security context
- `trace` -- tracing status
- `unique` -- unique access
- `chunken`, `chunkv`, `chunknum`, `chunkstrb` -- chunking info
- `poison` -- poison indicator

## Convenience Functions

### `create_simple_write_packets(id_val, addr, data, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

Create AW and W packets for a simple single-beat write.

### `create_simple_read_packet(id_val, addr, id_width, addr_width) -> AXI5Packet`

Create an AR packet for a simple single-beat read.

### `create_atomic_write_packets(id_val, addr, data, atop, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

Create AW and W packets for an atomic operation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `atop` | int | Atomic operation type: `0x10`=Store, `0x20`=Load, `0x30`=Swap, `0x31`=Compare |

### `create_tagged_write_packets(id_val, addr, data, tag, tagop, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

Create AW and W packets with Memory Tagging Extension support.

| Parameter | Type | Description |
|-----------|------|-------------|
| `tag` | int | Memory tag value |
| `tagop` | int | Tag operation: `0`=Invalid, `1`=Transfer, `2`=Update, `3`=Match |

## Packet Utility Functions

The `axi5_packet_utils` module provides additional helper functions:

### Address Packets
- `create_simple_read_packet(address, id_val, burst_len, size, burst_type, **kwargs)` -- AR packet
- `create_simple_write_address_packet(address, id_val, burst_len, size, burst_type, **kwargs)` -- AW packet

### Data Packets
- `create_simple_write_data_packet(data, last, strb, data_width, **kwargs)` -- W packet
- `create_simple_read_response_packet(data, resp, last, id_val, data_width, **kwargs)` -- R packet
- `create_simple_write_response_packet(resp, id_val, **kwargs)` -- B packet

### Burst Packets
- `create_burst_write_packets(id_val, start_addr, data_list, size, burst_type, **kwargs)` -- AW + W list
- `create_burst_read_response_packets(id_val, data_list, resp, **kwargs)` -- R list

### AXI5-Specific Packets
- `create_atomic_transaction_packets(id_val, addr, data, atop, data_width, **kwargs)` -- Atomic AW + W
- `create_tagged_write_packets(id_val, addr, data_list, tag, tagop, data_width, **kwargs)` -- MTE AW + W list
- `create_tagged_read_packet(id_val, addr, burst_len, tagop, **kwargs)` -- MTE AR
- `create_chunked_read_packet(id_val, addr, burst_len, **kwargs)` -- Chunked AR
- `create_secure_write_packets(id_val, addr, data, nsaid, mpam, mecid, data_width, **kwargs)` -- Security AW + W
- `create_traced_write_packets(id_val, addr, data, data_width, **kwargs)` -- Traced AW + W

## Usage Examples

### Example 1: Creating and Validating Packets

```python
from CocoTBFramework.components.axi5 import AXI5Packet

# Create an AW packet with atomic operation
aw = AXI5Packet.create_aw_packet(
    id=1, addr=0x1000, len=0, size=2, burst=1, atop=0x30
)
print(aw)  # "AXI5Packet(AW: id=1, addr=0x1000, len=0, atomic=AtomicSwap)"

# Validate protocol compliance
is_valid, errors = aw.validate_axi5_protocol()
assert is_valid, f"Protocol errors: {errors}"

# Get AXI5-specific feature info
features = aw.get_axi5_features()
assert features['is_atomic'] is True
assert features['atomic_type'] == 'AtomicSwap'
```

### Example 2: Working with MTE Packets

```python
from CocoTBFramework.components.axi5 import (
    create_tagged_write_packets, create_tagged_read_packet
)

# Create tagged write (MTE)
aw_pkt, w_pkts = create_tagged_write_packets(
    id_val=2, addr=0x3000,
    data_list=[0x11111111, 0x22222222],
    tag=0xA, tagop=2  # Update operation
)

# Create tagged read
ar_pkt = create_tagged_read_packet(
    id_val=3, addr=0x3000, burst_len=2, tagop=1  # Transfer operation
)
```

### Example 3: Security and Tracing Packets

```python
from CocoTBFramework.components.axi5 import (
    create_secure_write_packets, create_traced_write_packets
)

# Write with security context
aw_sec, w_sec = create_secure_write_packets(
    id_val=4, addr=0x5000, data=0xABCDEF01,
    nsaid=2, mpam=0x100, mecid=0x1234
)

# Write with tracing enabled
aw_trace, w_trace = create_traced_write_packets(
    id_val=5, addr=0x6000, data=0xFEEDFACE
)
```
